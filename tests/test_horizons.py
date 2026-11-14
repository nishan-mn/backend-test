import asyncio
import csv
from datetime import timedelta

import httpx
import pytest

from app.models import AnalysisRequest
from app.services.horizons import HorizonsClient, HorizonsError, build_parameters, normalize_longitude, parse_ephemeris
from app.services.visibility import analyze_visibility, midpoint_samples


@pytest.mark.parametrize("value,expected", [(-180, 180), (-30, 330), (0, 0), (32.5, 32.5), (180, 180)])
def test_longitude(value, expected):
    assert normalize_longitude(value) == expected


@pytest.mark.parametrize("target,azimuth,elevation", [(10, 20.957186, 6.029127), (399, 319.974447, 6.884094)])
def test_real_captured_report(mission, reports, target, azimuth, elevation):
    result = parse_ephemeris(reports[target], target, mission, midpoint_samples(mission))
    assert result.reference_frame == "MEAN_ME (high precision)"
    assert result.radii_km == (1737.4, 1737.4, 1737.4)
    assert result.positions[0].azimuth_deg == azimuth
    assert result.positions[0].elevation_deg == elevation


def test_verified_parameters(payload):
    mission = AnalysisRequest(**(payload | {"longitude_deg": -30, "duration_hours": 144}))
    params = build_parameters(10, mission, midpoint_samples(mission))
    assert params["CENTER"] == "'coord@301'"
    assert params["SITE_COORD"] == "'330.000000000000,-85.200000000000,0'"
    assert params["START_TIME"] == "'2026-11-20 00:30:00'"
    assert params["STOP_TIME"] == "'2026-11-25 23:30:00'"
    assert params["STEP_SIZE"] == "'1 h'"
    assert "TLIST" not in params
    assert params["QUANTITIES"] == "'4'"
    assert params["ELEV_CUT"] == "'-90'"
    assert params["TIME_ZONE"] == "'+00:00'"


def test_one_interval_tlist(mission):
    params = build_parameters(399, mission, midpoint_samples(mission))
    assert params["TLIST"] == "'2026-11-20 00:30:00'"
    assert params["TLIST_TYPE"] == "'CAL'"
    assert params["COMMAND"] == "'399'"
    assert not {"START_TIME", "STOP_TIME", "STEP_SIZE"} & params.keys()


def test_millisecond_request(payload):
    mission = AnalysisRequest(**(payload | {"start_utc": "2026-11-20T00:00:17.123Z"}))
    params = build_parameters(10, mission, midpoint_samples(mission))
    assert params["TLIST"] == "'2026-11-20 00:30:17.123'"
    assert params["TIME_DIGITS"] == "'FRACSEC'"


def test_whole_seconds_report_format(mission, reports):
    report = reports[10].replace("Date__(UT)__HR:MN:SC.fff", "Date__(UT)__HR:MN:SS")
    report = report.replace("2026-Nov-20 00:30:00.000,", "2026-Nov-20 00:30:00,")
    result = parse_ephemeris(report, 10, mission, midpoint_samples(mission))
    assert result.positions[0].timestamp == midpoint_samples(mission)[0]


@pytest.mark.parametrize("old,new", [
    ("$$SOE", "MISSING"), ("$$EOE", "MISSING"),
    ("Sun (10)", "Earth (399)"), ("Moon (301)", "Earth (399)"),
    ("(user defined site below)", "BODY CENTER"),
    ("32.5, -85.2, 0.0", "33.5, -85.2, 0.0"),
    ("32.5, -85.2, 0.0", "32.5, -84.2, 0.0"),
    ("32.5, -85.2, 0.0", "32.5, -85.2, 1.0"),
    ("32.5, -85.2, 0.0", "nan, -85.2, 0.0"),
    ("MEAN_ME (high precision)", "ITRF93"), ("1737.4", "6378.0"),
    ("NO (AIRLESS)", "YES (REFRACTED)"), ("Gregorian", "Mixed"),
    ("Units: DEGREES", "Units: RADIANS"),
    ("Date__(UT)__", "Date__(TT)__"), ("Azi_(a-app)", "Azi_(r-app)"),
    ("6.029127", "n.a."), ("6.029127", "NaN"), ("6.029127", "inf"),
    ("6.029127", "91.0"), ("20.957186", "-1.0"), ("20.957186", "361.0"),
    ("2026-Nov-20 00:30:00.000,*,i", "2026-Nov-20 00:31:00.000,*,i"),
    ("2026-Nov-20 00:30:00.000,*,i", "2026-Wow-20 00:30:00.000,*,i"),
    (",*,i,", ",*,i,extra,"),
])
def test_rejects_bad_report(mission, reports, old, new):
    with pytest.raises(HorizonsError):
        parse_ephemeris(reports[10].replace(old, new), 10, mission, midpoint_samples(mission))


@pytest.mark.parametrize("records", ["", "\n", "\ninvalid row\n"])
def test_missing_or_malformed_records(mission, reports, records):
    header, rest = reports[10].split("$$SOE")
    _, footer = rest.split("$$EOE")
    with pytest.raises(HorizonsError):
        parse_ephemeris(header + "$$SOE" + records + "$$EOE" + footer, 10, mission, midpoint_samples(mission))


def test_missing_duplicate_or_extra_samples(mission, reports):
    expected = midpoint_samples(mission)
    with pytest.raises(HorizonsError, match="sample count"):
        parse_ephemeris(reports[10], 10, mission, expected + [expected[0] + timedelta(hours=1)])
    header, rest = reports[10].split("$$SOE")
    records, footer = rest.split("$$EOE")
    with pytest.raises(HorizonsError, match="sample count"):
        duplicated = "\n" + records.strip() + "\n" + records.strip() + "\n"
        parse_ephemeris(header + "$$SOE" + duplicated + "$$EOE" + footer, 10, mission, expected)


def test_column_positions_are_discovered(mission, reports):
    report = reports[10]
    header, rest = report.split("$$SOE")
    records, footer = rest.split("$$EOE")
    headings = next(line for line in header.splitlines() if "Date__(UT)__" in line)
    columns = next(csv.reader([headings]))
    row = next(csv.reader([records.strip()]))
    columns[3], columns[4] = columns[4], columns[3]
    row[3], row[4] = row[4], row[3]
    modified = header.replace(headings, ",".join(columns)) + "$$SOE\n" + ",".join(row) + "\n$$EOE" + footer
    result = parse_ephemeris(modified, 10, mission, midpoint_samples(mission))
    assert result.positions[0].elevation_deg == 6.029127


@pytest.mark.parametrize("failure,status", [
    (httpx.ReadTimeout, 504), (httpx.ConnectTimeout, 504), (httpx.ConnectError, 503),
    (httpx.RemoteProtocolError, 503), (429, 503), (503, 503), (500, 502), (400, 502),
    ("NASA scientific error", 502),
])
def test_upstream_failures(mission, failure, status):
    def handler(request):
        if isinstance(failure, type):
            raise failure("private upstream details", request=request)
        if isinstance(failure, int):
            return httpx.Response(failure, text="private upstream details")
        return httpx.Response(200, text=failure)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            await HorizonsClient(http).get_series(10, mission, midpoint_samples(mission))

    with pytest.raises(HorizonsError) as error:
        asyncio.run(run())
    assert error.value.status_code == status
    assert "private" not in str(error.value)


def test_application_header_overrides_supplied_client(mission, reports, monkeypatch):
    monkeypatch.setenv("LUNAR_COMPASS_CONTACT", "header-test@example.invalid")
    headers = []

    def handler(request):
        headers.append(request.headers["User-Agent"])
        target = int(request.url.params["COMMAND"].strip("'"))
        return httpx.Response(200, text=reports[target])

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), headers={"User-Agent": "Another module"}
        ) as http:
            await analyze_visibility(mission, http)
            assert http.headers["User-Agent"] == "Another module"

    asyncio.run(run())
    assert headers == ["Lunar-Compass/1.0.0 (Lunar Compass; contact: header-test@example.invalid)"] * 2


@pytest.mark.parametrize("contact", [None, "", "  ", "bad\r\nInjected: header", "\ud800", "bad(contact)", "x" * 257])
def test_missing_or_unsafe_contact_never_sends(mission, monkeypatch, contact):
    if contact is None:
        monkeypatch.delenv("LUNAR_COMPASS_CONTACT", raising=False)
    else:
        monkeypatch.setenv("LUNAR_COMPASS_CONTACT", contact)

    def handler(request):
        pytest.fail("No NASA request is allowed without safe application identification")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            await analyze_visibility(mission, http)

    with pytest.raises(HorizonsError, match="LUNAR_COMPASS_CONTACT") as error:
        asyncio.run(run())
    assert error.value.status_code == 503


@pytest.mark.parametrize("supplied_clients", [True, False])
def test_overlapping_analyses_share_gate_through_body_read(mission, reports, monkeypatch, supplied_clients):
    active = maximum = 0
    calls = []

    class SlowBody(httpx.AsyncByteStream):
        def __init__(self, report):
            self.report = report

        async def __aiter__(self):
            nonlocal active
            try:
                await asyncio.sleep(0.02)
                yield self.report.encode()
            finally:
                active -= 1

    async def handler(request):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        target = int(request.url.params["COMMAND"].strip("'"))
        calls.append(target)
        return httpx.Response(200, stream=SlowBody(reports[target]))

    original_client = httpx.AsyncClient
    if not supplied_clients:
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(
            transport=httpx.MockTransport(handler), **kwargs
        ))

    async def run():
        if not supplied_clients:
            return await asyncio.gather(analyze_visibility(mission), analyze_visibility(mission))
        async with original_client(transport=httpx.MockTransport(handler)) as first:
            async with original_client(transport=httpx.MockTransport(handler)) as second:
                return await asyncio.gather(analyze_visibility(mission, first), analyze_visibility(mission, second))

    first, second = asyncio.run(asyncio.wait_for(run(), timeout=3))
    assert maximum == 1
    assert active == 0
    assert sorted(calls) == [10, 10, 399, 399]
    assert first == second
    for result in (first, second):
        assert result.timeline[0].sample_utc == midpoint_samples(mission)[0]
        assert result.timeline[0].sun_elevation_deg == 6.029127
        assert result.timeline[0].earth_elevation_deg == 6.884094
        assert result.metrics.model_dump() == dict(
            sunlight_percent=100, earth_visibility_percent=100,
            longest_darkness_hours=0, longest_earth_gap_hours=0,
        )


def test_gate_releases_on_holder_and_waiter_cancellation(mission, reports):
    async def run():
        reading = asyncio.Event()
        calls = 0
        closed = False

        class BlockedBody(httpx.AsyncByteStream):
            async def __aiter__(self):
                reading.set()
                await asyncio.Event().wait()
                yield b"unreachable"

            async def aclose(self):
                nonlocal closed
                closed = True

        def handler(request):
            nonlocal calls
            calls += 1
            return httpx.Response(200, stream=BlockedBody()) if calls == 1 else httpx.Response(200, text=reports[10])

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            horizons = HorizonsClient(http)
            holder = asyncio.create_task(horizons.get_series(10, mission, midpoint_samples(mission)))
            await reading.wait()
            waiter = asyncio.create_task(horizons.get_series(10, mission, midpoint_samples(mission)))
            await asyncio.sleep(0.03)
            assert calls == 1
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            assert not holder.done()
            holder.cancel()
            with pytest.raises(asyncio.CancelledError):
                await holder
            result = await horizons.get_series(10, mission, midpoint_samples(mission))
            assert result.positions[0].elevation_deg == 6.029127
        assert closed
        assert calls == 2

    asyncio.run(asyncio.wait_for(run(), timeout=3))


@pytest.mark.parametrize("failure", ["body", "http", "parse", "programming"])
def test_gate_releases_on_failures(mission, reports, failure):
    calls = 0

    class FailedBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise httpx.ReadTimeout("simulated read failure")
            yield b"unreachable"

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            if failure == "programming":
                raise RuntimeError("simulated programming error")
            if failure == "body":
                return httpx.Response(200, stream=FailedBody())
            return httpx.Response(500 if failure == "http" else 200, text="bad report")
        return httpx.Response(200, text=reports[10])

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            horizons = HorizonsClient(http)
            with pytest.raises(RuntimeError if failure == "programming" else HorizonsError):
                await horizons.get_series(10, mission, midpoint_samples(mission))
            assert (await horizons.get_series(10, mission, midpoint_samples(mission))).positions[0].elevation_deg == 6.029127

    asyncio.run(asyncio.wait_for(run(), timeout=3))
