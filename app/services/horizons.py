"""NASA observer requests and strict parsing of QUANTITIES=4 CSV reports."""

import asyncio
import csv
import math
import os
import re
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

import httpx

from app import __version__
from app.models import AnalysisRequest

HORIZONS_URL = "https://ssd.jpl.nasa.gov/api/horizons.api"
TIMEOUT = httpx.Timeout(45.0, connect=10.0)
_NASA_REQUEST_LOCK = threading.Lock()


class HorizonsError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


@asynccontextmanager
async def _nasa_request_gate() -> AsyncIterator[None]:
    # One process-wide gate, including callers on different event loops/threads.
    # Never block an event loop or leave a background acquisition behind on cancellation.
    while not _NASA_REQUEST_LOCK.acquire(blocking=False):
        await asyncio.sleep(0.01)
    try:
        yield
    finally:
        _NASA_REQUEST_LOCK.release()


def _user_agent() -> str:
    contact = os.getenv("LUNAR_COMPASS_CONTACT", "").strip()
    if not contact:
        raise HorizonsError("Set LUNAR_COMPASS_CONTACT to a real team email or contact URL before using NASA", 503)
    if len(contact) > 256 or any(not 32 <= ord(char) <= 126 or char in "()\\" for char in contact):
        raise HorizonsError("LUNAR_COMPASS_CONTACT must be printable ASCII without parentheses or backslashes", 503)
    return f"Lunar-Compass/{__version__} (Lunar Compass; contact: {contact})"


@dataclass(frozen=True)
class Position:
    timestamp: datetime
    azimuth_deg: float
    elevation_deg: float


@dataclass(frozen=True)
class Ephemeris:
    positions: tuple[Position, ...]
    reference_frame: str
    radii_km: tuple[float, float, float]


def normalize_longitude(longitude_deg: float) -> float:
    return longitude_deg % 360.0


def build_parameters(
    target: int, request: AnalysisRequest, samples: Sequence[datetime]
) -> dict[str, str]:
    if target not in (10, 399) or not samples:
        raise ValueError("A Sun or Earth target and at least one sample are required")
    settings = {
        "COMMAND": str(target),
        "CENTER": "coord@301",
        "EPHEM_TYPE": "OBSERVER",
        "COORD_TYPE": "GEODETIC",
        "SITE_COORD": f"{normalize_longitude(request.longitude_deg):.12f},{request.latitude_deg:.12f},0",
        "QUANTITIES": "4",
        "APPARENT": "AIRLESS",
        "TIME_TYPE": "UT",
        "TIME_ZONE": "+00:00",
        "CAL_FORMAT": "CAL",
        "CAL_TYPE": "GREGORIAN",
        "TIME_DIGITS": "FRACSEC" if samples[0].microsecond else "SECONDS",
        "CSV_FORMAT": "YES",
        "ELEV_CUT": "-90",
        "SKIP_DAYLT": "NO",
        "R_T_S_ONLY": "NO",
        "MAKE_EPHEM": "YES",
        "OBJ_DATA": "NO",
    }
    # Horizons rejects equal START/STOP times. A one-hour mission uses one TLIST epoch.
    precision = "milliseconds" if samples[0].microsecond else "seconds"
    first = samples[0].replace(tzinfo=None).isoformat(sep=" ", timespec=precision)
    last = samples[-1].replace(tzinfo=None).isoformat(sep=" ", timespec=precision)
    if len(samples) == 1:
        settings.update(TLIST=first, TLIST_TYPE="CAL")
    else:
        settings.update(
            START_TIME=first,
            STOP_TIME=last,
            STEP_SIZE="1 h",
        )
    return {"format": "text", **{key: f"'{value}'" for key, value in settings.items()}}


def _header_value(header: str, label: str) -> str:
    matches = re.findall(rf"^{re.escape(label)}\s*:\s*(.+)$", header, re.MULTILINE)
    if len(matches) != 1:
        raise HorizonsError(f"Horizons report has missing or ambiguous {label} metadata")
    return matches[0].strip()


def _triplet(value: str) -> tuple[float, float, float]:
    try:
        parts = value.split("{")[0].replace("km", "").split(",")
        numbers = tuple(float(part.strip()) for part in parts)
        if len(numbers) != 3 or not all(math.isfinite(n) for n in numbers):
            raise ValueError
        return numbers
    except ValueError as exc:
        raise HorizonsError("Horizons returned invalid observer metadata") from exc


def _verify_observer(
    header: str, target: int, request: AnalysisRequest
) -> tuple[str, tuple[float, float, float]]:
    name = {10: "Sun", 399: "Earth"}[target]
    if not re.match(rf"{name}\s+\({target}\)(?:\s|$)", _header_value(header, "Target body name")):
        raise HorizonsError("Horizons returned the wrong target body")
    if not re.match(r"Moon\s+\(301\)(?:\s|$)", _header_value(header, "Center body name")):
        raise HorizonsError("Horizons observer is not on the Moon")
    if _header_value(header, "Center-site name") != "(user defined site below)":
        raise HorizonsError("Horizons did not use the requested surface observer")
    site = _header_value(header, "Center geodetic")
    if "{E-lon(deg),Lat(deg),Alt(km)}" not in site:
        raise HorizonsError("Horizons observer coordinate units are unexpected")
    longitude, latitude, altitude = _triplet(site)
    # Header coordinates are rounded by Horizons; compare at its printed precision.
    longitude_error = abs((longitude - request.longitude_deg + 180) % 360 - 180)
    if longitude_error > 1e-5 or abs(latitude - request.latitude_deg) > 1e-5 or abs(altitude) > 1e-4:
        raise HorizonsError("Horizons observer coordinates do not match the requested location")
    frame = _header_value(header, "Center pole/equ")
    if "{East-longitude positive}" not in frame:
        raise HorizonsError("Horizons lunar longitude convention is unexpected")
    frame = frame.split("{")[0].strip()
    if frame not in ("MEAN_ME (high precision)", "MOON_ME", "MOON_ME (high precision)"):
        raise HorizonsError("Horizons did not use the supported lunar mean-Earth reference frame")
    radii = _triplet(_header_value(header, "Center radii"))
    if any(abs(radius - 1737.4) > 0.001 for radius in radii):
        raise HorizonsError("Horizons lunar reference ellipsoid is unexpected")
    if _header_value(header, "Atmos refraction") != "NO (AIRLESS)":
        raise HorizonsError("Horizons did not return airless apparent angles")
    if _header_value(header, "Calendar mode") != "Gregorian":
        raise HorizonsError("Horizons did not use the requested Gregorian calendar")
    return frame, radii


def _parse_timestamp(value: str) -> datetime:
    # Map English month labels explicitly: parsing must not depend on server locale.
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    match = re.fullmatch(r"(\d{4})-([A-Za-z]{3})-(\d{2}) (\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?)", value)
    if match is None:
        raise ValueError("Invalid Horizons calendar timestamp")
    year, month, day, time = match.groups()
    month_number = months.index(month) + 1
    return datetime.fromisoformat(f"{year}-{month_number:02}-{day}T{time}+00:00")


def parse_ephemeris(
    report: str, target: int, request: AnalysisRequest, expected: Sequence[datetime]
) -> Ephemeris:
    if report.count("$$SOE") != 1 or report.count("$$EOE") != 1:
        raise HorizonsError("Horizons returned no usable ephemeris; check the requested date or retry later")
    header, remainder = report.split("$$SOE")
    if "$$EOE" not in remainder:
        raise HorizonsError("Horizons returned invalid ephemeris delimiters")
    records, footer = remainder.split("$$EOE")
    frame, radii = _verify_observer(header, target, request)
    if "Units: DEGREES" not in footer:
        raise HorizonsError("Horizons azimuth/elevation units could not be verified")
    headings = [line for line in header.splitlines() if line.lstrip().startswith("Date__(UT)__")]
    if len(headings) != 1:
        raise HorizonsError("Horizons returned missing or unexpected UTC table headings")
    try:
        columns = [cell.strip() for cell in next(csv.reader(headings, strict=True))]
        # Horizons may omit zero seconds for regular steps even with TIME_DIGITS=SECONDS.
        if columns[0] not in ("Date__(UT)__HR:MN", "Date__(UT)__HR:MN:SS", "Date__(UT)__HR:MN:SC.fff"):
            raise ValueError("Unexpected timestamp precision")
        if columns.count("Azi_(a-app)") != 1 or columns.count("Elev_(a-app)") != 1:
            raise ValueError("Missing apparent angular columns")
        azimuth_index = columns.index("Azi_(a-app)")
        elevation_index = columns.index("Elev_(a-app)")
        positions = []
        for row in csv.reader(records.strip().splitlines(), strict=True):
            if len(row) != len(columns):
                raise ValueError("Malformed record")
            timestamp = _parse_timestamp(row[0].strip())
            azimuth = float(row[azimuth_index])
            elevation = float(row[elevation_index])
            if not math.isfinite(azimuth) or not 0 <= azimuth <= 360:
                raise ValueError("Invalid azimuth")
            if not math.isfinite(elevation) or not -90 <= elevation <= 90:
                raise ValueError("Invalid elevation")
            positions.append(Position(timestamp, azimuth, elevation))
    except (ValueError, csv.Error) as exc:
        raise HorizonsError("Horizons returned malformed or missing azimuth/elevation data") from exc
    if [position.timestamp for position in positions] != list(expected):
        raise HorizonsError("Horizons sample count or UTC timestamps do not match the mission midpoints")
    return Ephemeris(tuple(positions), frame, radii)


class HorizonsClient:
    def __init__(self, http: httpx.AsyncClient):
        self.http = http

    async def get_series(
        self, target: int, request: AnalysisRequest, samples: Sequence[datetime]
    ) -> Ephemeris:
        headers = {"User-Agent": _user_agent()}
        try:
            async with _nasa_request_gate():
                response = await self.http.get(
                    HORIZONS_URL, params=build_parameters(target, request, samples),
                    headers=headers, timeout=TIMEOUT,
                )
                # AsyncClient.get reads the entire body before returning (stream=False).
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise HorizonsError("NASA JPL Horizons timed out; retry later", 504) from exc
        except httpx.HTTPStatusError as exc:
            status = 503 if exc.response.status_code in (429, 503) else 502
            raise HorizonsError("NASA JPL Horizons returned an HTTP error; retry later", status) from exc
        except httpx.RequestError as exc:
            raise HorizonsError("NASA JPL Horizons is unavailable; retry later", 503) from exc
        return parse_ephemeris(response.text, target, request, samples)
