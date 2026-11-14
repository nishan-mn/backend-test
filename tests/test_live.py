"""Explicitly opt in with: python -m pytest -m live --live-horizons -v -s."""

import asyncio
import csv
from itertools import groupby

import httpx
import pytest

from app.models import AnalysisRequest
from app.services.visibility import analyze_visibility, midpoint_samples

pytestmark = pytest.mark.live


@pytest.mark.parametrize("latitude,longitude,duration,start,earth_sign", [
    (-85.2, 32.5, 144, "2026-11-20T00:00:00Z", None),
    (-85.2, 32.5, 1, "2026-11-20T00:00:00Z", 1),
    (0, -30, 1, "2026-11-20T00:00:00Z", 1),
    (0, 180, 1, "2026-11-20T00:00:00Z", -1),
    (90, -180, 1, "2026-11-20T00:00:00Z", None),
    (-90, 0, 1, "2026-11-20T00:00:00Z", None),
    (-85.2, 32.5, 2, "2026-11-20T00:00:17.123Z", None),
    (20.123456789, -30.123456789, 2, "2026-11-20T00:00:17Z", None),
    (0, 0, 336, "2026-11-20T00:00:00Z", 1),
])
def test_live_observer_and_metrics(latitude, longitude, duration, start, earth_sign):
    mission = AnalysisRequest(latitude_deg=latitude, longitude_deg=longitude, duration_hours=duration, start_utc=start)
    reports = []

    async def capture(response):
        await response.aread()
        reports.append(response.text)

    async def run():
        async with httpx.AsyncClient(event_hooks={"response": [capture]}) as http:
            return await analyze_visibility(mission, http)

    result = asyncio.run(run())
    assert len(reports) == 2
    assert len(result.timeline) == duration
    assert [row.sample_utc for row in result.timeline] == midpoint_samples(mission)
    for report, target_name, prefix in zip(reports, ("Sun (10)", "Earth (399)"), ("sun", "earth"), strict=True):
        assert f"Target body name: {target_name}" in report
        assert "Center body name: Moon (301)" in report
        assert "Center geodetic" in report
        assert "MEAN_ME" in report or "MOON_ME" in report
        header, body = report.split("$$SOE")
        headings = next(line for line in header.splitlines() if "Date__(UT)__" in line)
        columns = [cell.strip() for cell in next(csv.reader([headings]))]
        rows = list(csv.reader(body.split("$$EOE")[0].strip().splitlines()))
        elevations = [float(row[columns.index("Elev_(a-app)")]) for row in rows]
        azimuths = [float(row[columns.index("Azi_(a-app)")]) for row in rows]
        assert elevations == [getattr(row, f"{prefix}_elevation_deg") for row in result.timeline]
        assert azimuths == [getattr(row, f"{prefix}_azimuth_deg") for row in result.timeline]
        flags = [elevation > 0 for elevation in elevations]
        percentage = 100 * sum(flags) / duration
        longest_gap = max((len(list(group)) for visible, group in groupby(flags) if not visible), default=0)
        assert getattr(result.metrics, "sunlight_percent" if prefix == "sun" else "earth_visibility_percent") == percentage
        assert getattr(result.metrics, "longest_darkness_hours" if prefix == "sun" else "longest_earth_gap_hours") == longest_gap
    if earth_sign is not None:
        assert all(row.earth_elevation_deg * earth_sign > 0 for row in result.timeline)
    print({"location": result.location.model_dump(), "duration_hours": duration,
           "metrics": result.metrics.model_dump(), "first_sample": result.timeline[0].model_dump(mode="json"),
           "last_sample": result.timeline[-1].sample_utc.isoformat()})
