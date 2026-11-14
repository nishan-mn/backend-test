# Lunar Compass visibility engine

Python 3.11+ / FastAPI / Pydantic / HTTPX backend for Sun and direct Earth
visibility at arbitrary lunar coordinates. It makes two NASA JPL Horizons
observer requests per successful analysis, then calculates four metrics and an
hourly timeline locally. There is no fallback or generated scientific data.

## Run

From this folder in PowerShell, with Python 3.11+ installed:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:LUNAR_COMPASS_CONTACT = Read-Host "Real team email or public contact URL"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

A working `.venv` was created during implementation. On this machine Python
was not on PATH; that environment uses the installed bundled Python 3.12.14.
The last command above works directly here. For a fresh checkout, use your
Python installation to create a new environment; virtual environments are not portable.

Before sending NASA requests, set `LUNAR_COMPASS_CONTACT` to a real, monitored
team email or public contact URL. It must be printable ASCII, at most 256
characters, without parentheses or backslashes. There is no default contact.
Missing/invalid identification returns 503 before any outbound request; health,
documentation and input validation still work. Contact information is sent to NASA,
so do not put credentials or secrets in this setting.

The outgoing header is `Lunar-Compass/1.0.0 (Lunar Compass; contact: CONTACT)`.
The version comes from `app.__version__`, also used by FastAPI. The NASA request
boundary sets this header explicitly, including for caller-supplied HTTPX clients;
it does not change that client's default headers. Offline tests use a reserved
`.invalid` address with simulated transports only. Live tests require the real
environment setting and never substitute a test contact.

Deploy **one worker process and one backend instance** initially:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --workers 1
```

All engine callers share one process-wide NASA gate, held through response-body
reading and released on errors or cancellation. Waiting yields to the event loop;
the gate also works across event loops in the same process. It does not coordinate
separate worker processes or backend instances. Use `--reload` only for local
development, with no second running instance.

Open [interactive API docs](http://127.0.0.1:8000/docs).
`GET /health` returns `{"status":"ok"}` without contacting NASA.

Default CORS origins are `http://localhost:3000` and `http://localhost:5173`.
Set an explicit comma-separated list before startup:

```powershell
$env:ALLOWED_ORIGINS = "http://localhost:5173,https://your-frontend.example"
```

An empty list disables cross-origin access. Wildcards are rejected.

## Analyze

`POST /api/analyze`, `Content-Type: application/json`:

```json
{
  "latitude_deg": -85.2,
  "longitude_deg": 32.5,
  "start_utc": "2026-11-20T00:00:00Z",
  "duration_hours": 144
}
```

```powershell
$body = @{latitude_deg=-85.2; longitude_deg=32.5; start_utc="2026-11-20T00:00:00Z"; duration_hours=144} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/analyze" -ContentType "application/json" -Body $body
```

| Input | Rules |
| --- | --- |
| `latitude_deg` | Finite JSON number, -90 to +90; north positive |
| `longitude_deg` | Finite JSON number, -180 to +180; east positive |
| `start_utc` | ISO 8601 date/time with seconds and `Z` or `+00:00`; optional milliseconds |
| `duration_hours` | JSON integer, 1–336 inclusive; strings, fractions and booleans rejected |

All four fields are required; unknown fields are rejected. Times before 1962
are rejected because Horizons' earlier `UT` is UT1 rather than UTC. Submillisecond
precision and leap-second notation are unsupported; nothing is silently rounded.
Dates outside NASA's supported mean-Earth model fail explicitly.

The response contains `location`, `start_utc`, `end_utc`, `duration_hours`,
`sampling_minutes`, four `metrics`, a complete `timeline`, and explanatory `model`
metadata. Each timeline entry contains its interval bounds, midpoint, both
azimuths/elevations in degrees and two visibility booleans. Original longitude is
preserved in `location`; only the NASA request normalizes it to [0, 360).

Percentages count visible hourly intervals / total intervals × 100. Gaps are
the longest consecutive invisible intervals, measured in hours and clipped to
the mission boundaries. **Elevation must be strictly greater than zero.**
For 144 hours there are exactly 144 samples, from November 20 at 00:30 UTC to
November 25 at 23:30 UTC, with mission end November 26 at 00:00 UTC.

Errors use `detail`: 422 input validation (error list with `type`, `loc`, `msg`),
502 unusable NASA data/HTTP failure, 503 missing/invalid application contact,
connection failure or NASA 429/503, and 504 timeout. Validation errors omit raw
`input` and exception `ctx`; unsafe text/bytes in metadata are escaped safely.
There are no retries; connect timeout is 10 seconds and HTTP read/write/pool
timeouts are 45 seconds per request. Missing, malformed, reordered or mismatched
samples fail the whole analysis. They never count as invisible.

## Scientific model

Source: [NASA Horizons API](https://ssd-api.jpl.nasa.gov/doc/horizons.html) and
[official manual](https://ssd.jpl.nasa.gov/horizons/manual.html).
Requests use the following settings (values are quoted and URL-encoded by HTTPX):

```text
format=text; COMMAND='10' or '399'; CENTER='coord@301'
EPHEM_TYPE='OBSERVER'; COORD_TYPE='GEODETIC'; SITE_COORD='east_lon,lat,0'
QUANTITIES='4'; APPARENT='AIRLESS'; TIME_TYPE='UT'; TIME_ZONE='+00:00'
CAL_FORMAT='CAL'; CAL_TYPE='GREGORIAN'; TIME_DIGITS='SECONDS'
CSV_FORMAT='YES'; ELEV_CUT='-90'; SKIP_DAYLT='NO'; R_T_S_ONLY='NO'
MAKE_EPHEM='YES'; OBJ_DATA='NO'
START_TIME=first midpoint; STOP_TIME=last midpoint; STEP_SIZE='1 h'
```

A one-hour mission uses one calendar `TLIST` with `TLIST_TYPE='CAL'`, without
START/STOP/STEP. Millisecond starts use `TIME_DIGITS='FRACSEC'`. NASA emits
minute, second or millisecond table headings; all are parsed by heading and
every resulting UTC time must equal the expected midpoint exactly.

Coordinates must use the lunar **DE421 mean-Earth / mean rotation axis frame**,
reported by the live service as `MEAN_ME (high precision)` (the manual also uses
`MOON_ME`). The backend verifies the target, Moon observer, geodetic coordinates,
east-positive convention, airless setting, reference model and lunar radii
(1737.4 km on all axes in the captured reports). Unsupported frame changes are
rejected, including NASA's lower-precision model outside its mean-Earth coverage.

Ullas must verify the GLB's orientation, prime meridian and north pole against
known lunar landmarks before supplying coordinates. GLB compatibility has not
been verified here; the engine does not load the GLB. Azimuth runs clockwise
from north (0°), through east (90°); at a pole its convention depends on the
selected longitude.

Altitude 0 km on NASA's reference ellipsoid is an approximation. This is
body-center visibility above a local zero-degree horizon using apparent,
airless angles. Hourly midpoint estimates do not resolve exact rise/set times
or short events. No terrain, finite-disc, eclipse/occultation, panel, radio,
relay or landing-safety models are included. Visibility does not guarantee
power, communication or safe landing. Python interval arithmetic does not
model leap seconds; future UTC predictions also depend on NASA's current
leap-second assumptions.

## Reuse and files

```python
from app.models import AnalysisRequest
from app.services.visibility import analyze_visibility

# Inside an async caller; pass a shared HTTPX AsyncClient optionally.
result = await analyze_visibility(AnalysisRequest(
    latitude_deg=-85.2, longitude_deg=32.5,
    start_utc="2026-11-20T00:00:00Z", duration_hours=144,
))
```

`app/main.py` exposes the API; `app/models.py` defines the contract.
`app/services/horizons.py` handles NASA requests and verified CSV parsing;
`visibility.py` assembles intervals and `metrics.py` computes the four metrics.
`tests/` holds offline checks, captured NASA fixtures and optional live tests.
No other Lunar Compass modules or frontend components are implemented.

## Tests and verified results

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest tests/test_live.py --live-horizons -v -s
```

The default suite needs no network. Fixtures are actual reports captured on
November 13, 2026 at -85.2°, 32.5° east for one epoch and 144 epochs; malformed
variants and simple synthetic booleans are used only in tests. Production never
reads fixtures. Live tests are skipped unless explicitly enabled.

After the request-coordination, identification and validation-error repairs:
**151 offline tests passed; 9 live NASA tests passed on November 14, 2026**. New checks cover overlapping
analyses (maximum one upstream request, including body reads), supplied and
engine-created clients, cancellation, failure recovery, outgoing identification,
and malformed strings/bytes in validation data. The real six-day request through
the running FastAPI server also passed with 144 entries from `2026-11-20T00:30:00Z`
through `2026-11-25T23:30:00Z`, ending at `2026-11-26T00:00:00Z`. Set a real
contact before running the live command above; contact values are intentionally
not stored in this repository.

Original implementation verification on November 13, 2026: **126 offline tests
passed; 9 live tests passed**. The scientific calculations and fixtures have not
changed in the repairs.
Live checks cover six-day and maximum-duration series, a single epoch, near/far
sides, both poles, longitude normalization, nonzero seconds and milliseconds.
They inspect actual report metadata and independently recalculate metrics from
CSV columns. The offline suite emits one upstream Starlette TestClient HTTPX
deprecation warning; tests still pass. `pip check` found no broken requirements.
This is API/report verification, not an independent astronomical-model validation
or a separate comparison against the graphical Horizons interface.

During that original verification, NASA returned 100% sunlight and 100% Earth
visibility, with both longest gaps 0 hours. Sun elevations were 4.494109° to
6.337622° and Earth elevations 6.884094° to 10.142114°. A separate 336-hour
analysis at 0°, 0° from the same start returned 84.52380952380952% sunlight,
a 52-hour longest darkness interval, 100% Earth visibility and zero Earth gap.

Below is a **complete one-hour response** for the same location and start,
with `duration_hours: 1`, using real NASA data verified during implementation:

```json
{
  "location": {"latitude_deg": -85.2, "longitude_deg": 32.5},
  "start_utc": "2026-11-20T00:00:00Z",
  "end_utc": "2026-11-20T01:00:00Z",
  "duration_hours": 1,
  "sampling_minutes": 60,
  "metrics": {
    "sunlight_percent": 100.0,
    "earth_visibility_percent": 100.0,
    "longest_darkness_hours": 0,
    "longest_earth_gap_hours": 0
  },
  "timeline": [{
    "interval_start_utc": "2026-11-20T00:00:00Z",
    "interval_end_utc": "2026-11-20T01:00:00Z",
    "sample_utc": "2026-11-20T00:30:00Z",
    "sun_azimuth_deg": 20.957186,
    "sun_elevation_deg": 6.029127,
    "earth_azimuth_deg": 319.974447,
    "earth_elevation_deg": 6.884094,
    "sun_visible": true,
    "earth_visible": true
  }],
  "model": {
    "type": "simplified_geometric_horizon",
    "horizon_degrees": 0,
    "site_altitude_km": 0,
    "terrain_obstruction_included": false,
    "sampling_method": "hourly_midpoints",
    "source": "NASA JPL Horizons",
    "lunar_reference_frame": "MEAN_ME (high precision)",
    "lunar_radii_km": [1737.4, 1737.4, 1737.4],
    "limitations": [
      "Body centers above a zero-degree local horizon; apparent airless angles.",
      "Altitude 0 km on the Horizons lunar reference ellipsoid is an approximation.",
      "Hourly midpoint estimates, not exact rise/set times; gaps are clipped to the mission.",
      "No terrain obstruction, finite body discs, or eclipse/occultation screening.",
      "Visibility does not guarantee usable solar power, communication, or landing safety."
    ]
  }
}
```
