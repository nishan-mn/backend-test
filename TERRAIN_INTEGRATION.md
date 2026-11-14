# Lunar Terrain API in the shared backend

The terrain endpoint is part of the team's existing FastAPI application in
`app/main.py`. Its router, service, and Pydantic models live in `app/` and are
imported as `app.terrain_router`, `app.terrain_service`, and
`app.terrain_models`. The existing visibility engine, mission routes,
middleware, lifespan, and error handlers remain in the same application.

## Dependencies

Install the complete shared backend and test dependencies from the repository
root:

```bash
python3 -m pip install -r requirements.txt
```

Terrain analysis needs NumPy and Rasterio in addition to the existing FastAPI
stack. Uvicorn launches the shared application; pytest and HTTPX support the
team test suite.

## NASA raster files

The NASA GSFC PGDA LOLA Site01 GeoTIFFs are local data and must not be copied
into Git. The service reads these files:

```text
Site01_final_adj_5mpp_surf.tif
Site01_final_adj_5mpp_slp.tif
```

Set `LUNAR_COMPASS_TERRAIN_DATA_DIR` to the directory containing both rasters
before starting the application. For this checkout, the original data can be
used directly with:

```bash
export LUNAR_COMPASS_TERRAIN_DATA_DIR="/Users/yuthikasharma/lunar-terrain-analysis/local_data/lola/site01"
```

Without that setting, the service looks in `app/local_data/lola/site01`.
Relative configured paths are resolved from the directory containing
`app/terrain_service.py`, not from the process working directory. The service
checks that both files exist and that their CRS, affine transform, dimensions,
and resolution match. Missing files produce HTTP 503.

## Endpoint

`POST /api/terrain/analyze`

```json
{
  "latitude_deg": -89.463158,
  "longitude_deg": 222.498015,
  "analysis_radius_m": 500
}
```

`analysis_radius_m` defaults to 500. The response includes normalized
coordinates, pixel elevation and slope, regional statistics, valid-data and
requested-area coverage, raster provenance and limitations, and warnings.
Invalid input returns HTTP 422; a grid mismatch returns HTTP 500.

The data are regional 5 m/pixel measurements, not global lunar coverage.
Coordinates outside Site01 return no terrain measurements. The raster
resolution does not resolve small rocks, slope is not a landing-safety
assessment, and elevation standard deviation is a DEM-derived roughness proxy,
not official NASA LDRM roughness.

## Run the shared application

From the repository root:

```bash
uvicorn app.main:app --reload
```

The shared Swagger UI is at <http://127.0.0.1:8000/docs>. The application
factory `create_app()` in `app/main.py` includes the terrain router alongside
the existing team routes.

## Run tests

```bash
python3 -m pytest -q
```

The terrain suite includes synthetic raster tests and a NASA reference
coordinate check. The latter runs when the configured raster directory
contains the real Site01 elevation raster; otherwise pytest reports that test
as skipped.
