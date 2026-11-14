"""Reusable lunar terrain analysis backed by local NASA LOLA GeoTIFFs."""
from __future__ import annotations

from pathlib import Path
import os
from typing import Any

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.warp import transform
from rasterio.windows import Window

MOON_RADIUS_M = 1_737_400.0
LUNAR_GEOGRAPHIC_CRS = CRS.from_proj4(
    f"+proj=longlat +a={MOON_RADIUS_M} +b={MOON_RADIUS_M} +no_defs +type=crs"
)
PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "local_data/lola/site01"
DATA_DIR_ENV_VAR = "LUNAR_COMPASS_TERRAIN_DATA_DIR"
ELEVATION_FILENAME = "Site01_final_adj_5mpp_surf.tif"
SLOPE_FILENAME = "Site01_final_adj_5mpp_slp.tif"
NASA_DATASET_URL = "https://pgda.gsfc.nasa.gov/products/78"
NASA_LIMITATIONS = [
    "The Site01 rasters are regional 5 m/pixel products; locations outside their footprint have no measurements.",
    "Elevation and slope are raster-derived measurements and do not resolve sub-pixel hazards such as small rocks.",
    "Slope values inherit the source product's method and uncertainty; they are not a landing-safety assessment.",
]
ROUGHNESS_WARNING = (
    "Elevation standard deviation is a DEM-derived roughness proxy only; it is not official NASA LDRM roughness "
    "and does not detect rocks or determine landing hazards."
)


class DatasetUnavailableError(FileNotFoundError):
    """Raised when required local terrain rasters are unavailable."""


class DatasetMismatchError(RuntimeError):
    """Raised when elevation and slope rasters do not describe the same grid."""


class TerrainService:
    def __init__(self, data_dir: str | Path | None = None):
        # Relative configured paths are anchored to this module, never the process CWD.
        configured_dir = data_dir or os.environ.get(DATA_DIR_ENV_VAR) or DEFAULT_DATA_DIR
        self.data_dir = Path(configured_dir).expanduser()
        if not self.data_dir.is_absolute():
            self.data_dir = PROJECT_ROOT / self.data_dir
        self.data_dir = self.data_dir.resolve()
        self.elevation_path = self.data_dir / ELEVATION_FILENAME
        self.slope_path = self.data_dir / SLOPE_FILENAME

    def _ensure_files(self) -> None:
        missing = [str(p) for p in (self.elevation_path, self.slope_path) if not p.is_file()]
        if missing:
            raise DatasetUnavailableError("Required terrain dataset file(s) missing: " + ", ".join(missing))

    @staticmethod
    def _check_grid_match(dem: rasterio.DatasetReader, slope: rasterio.DatasetReader) -> None:
        mismatch = []
        if dem.crs != slope.crs: mismatch.append("CRS")
        if dem.transform != slope.transform: mismatch.append("transform")
        if (dem.width, dem.height) != (slope.width, slope.height): mismatch.append("dimensions")
        if not np.allclose(dem.res, slope.res, rtol=0, atol=1e-9): mismatch.append("resolution")
        if mismatch:
            raise DatasetMismatchError("Elevation and slope rasters have mismatched " + ", ".join(mismatch))

    def analyze(self, latitude_deg: float, longitude_deg: float, analysis_radius_m: float = 500) -> dict[str, Any]:
        if not np.isfinite(latitude_deg) or not -90 <= latitude_deg <= 90:
            raise ValueError("latitude_deg must be finite and between -90 and 90 degrees")
        if not np.isfinite(longitude_deg):
            raise ValueError("longitude_deg must be finite")
        if not np.isfinite(analysis_radius_m) or analysis_radius_m <= 0:
            raise ValueError("analysis_radius_m must be finite and greater than 0 metres")
        self._ensure_files()

        longitude = float(longitude_deg) % 360.0
        with rasterio.open(self.elevation_path) as dem, rasterio.open(self.slope_path) as slope_ds:
            self._check_grid_match(dem, slope_ds)
            # The caller supplies east-positive lunar longitude. The source products document
            # stereographic X/Y in MOON_ME/DE421; see README for the remaining convention caveat.
            xs, ys = transform(LUNAR_GEOGRAPHIC_CRS, dem.crs, [longitude], [float(latitude_deg)])
            x, y = xs[0], ys[0]
            row, col = dem.index(x, y)
            resolution_x, resolution_y = map(abs, dem.res)
            in_raster = 0 <= row < dem.height and 0 <= col < dem.width
            output_row, output_col = (row, col) if in_raster else (None, None)
            result: dict[str, Any] = {
                "terrain_available": False,
                "location": {"latitude_deg": float(latitude_deg), "longitude_deg": longitude},
                "pixel": {"row": output_row, "column": output_col, "elevation_m": None, "slope_deg": None},
                "region": {
                    "analysis_radius_m": float(analysis_radius_m), "mean_elevation_m": None,
                    "elevation_range_m": None, "mean_slope_deg": None, "maximum_slope_deg": None,
                    "elevation_stddev_m_roughness_proxy": None, "valid_pixel_count": 0,
                    "total_pixel_count": 0, "valid_pixel_percentage": 0.0, "valid_data_percentage": 0.0,
                    "requested_area_coverage_percentage": 0.0, "coverage_status": "outside_raster",
                },
                "raster": {
                    "resolution_m": max(resolution_x, resolution_y), "crs": dem.crs.to_string(),
                    "dataset_provenance": "NASA GSFC PGDA LOLA Site01 adjusted elevation and slope GeoTIFFs; "
                    f"{self.elevation_path.name}, {self.slope_path.name}",
                    "dataset_source_url": NASA_DATASET_URL,
                    "dataset_limitations": NASA_LIMITATIONS,
                },
                "warnings": [ROUGHNESS_WARNING],
            }
            if not in_raster:
                result["warnings"].insert(0, "Coordinate lies outside the available raster coverage.")
                return result

            e = dem.read(1, window=Window(col, row, 1, 1), masked=True)[0, 0]
            s = slope_ds.read(1, window=Window(col, row, 1, 1), masked=True)[0, 0]
            if not np.ma.is_masked(e) and np.isfinite(e): result["pixel"]["elevation_m"] = float(e)
            if not np.ma.is_masked(s) and np.isfinite(s): result["pixel"]["slope_deg"] = float(s)
            result["terrain_available"] = result["pixel"]["elevation_m"] is not None and result["pixel"]["slope_deg"] is not None
            if not result["terrain_available"]:
                result["warnings"].append("The selected pixel has missing or invalid elevation or slope data.")

            radius_px_x = int(np.ceil(analysis_radius_m / resolution_x))
            radius_px_y = int(np.ceil(analysis_radius_m / resolution_y))
            left, right = max(0, col-radius_px_x), min(dem.width, col+radius_px_x+1)
            top, bottom = max(0, row-radius_px_y), min(dem.height, row+radius_px_y+1)
            window = Window(left, top, right-left, bottom-top)
            edata = dem.read(1, window=window, masked=True)
            sdata = slope_ds.read(1, window=window, masked=True)
            rows, cols = np.ogrid[top:bottom, left:right]
            circle = ((cols-col)*resolution_x)**2 + ((rows-row)*resolution_y)**2 <= analysis_radius_m**2
            inside = int(np.count_nonzero(circle))
            ev, sv = np.asarray(edata.data, dtype=float), np.asarray(sdata.data, dtype=float)
            em = np.ma.getmaskarray(edata) | ~np.isfinite(ev)
            sm = np.ma.getmaskarray(sdata) | ~np.isfinite(sv)
            good = circle & ~em & ~sm
            elevations, slopes = ev[good], sv[good]
            # Area fraction is estimated from the rasterized circle's cell area versus the
            # requested continuous circle area; valid-data percentage is conditional on raster coverage.
            requested_area = np.pi * float(analysis_radius_m) ** 2
            bounds = dem.bounds
            clipped = (x - analysis_radius_m < bounds.left or x + analysis_radius_m > bounds.right
                       or y - analysis_radius_m < bounds.bottom or y + analysis_radius_m > bounds.top)
            area_coverage = (min(100.0, inside * resolution_x * resolution_y / requested_area * 100.0)
                             if clipped else 100.0)
            region = result["region"]
            region.update(total_pixel_count=inside, valid_pixel_count=int(len(elevations)),
                          valid_pixel_percentage=round(100*len(elevations)/inside, 2) if inside else 0.0,
                          valid_data_percentage=round(100*len(elevations)/inside, 2) if inside else 0.0,
                          requested_area_coverage_percentage=round(area_coverage, 2),
                          coverage_status="edge_clipped" if clipped else "in_raster")
            if clipped:
                result["warnings"].append("The requested analysis circle is edge-clipped by raster bounds; regional statistics use available raster cells only.")
            if len(elevations):
                region.update(mean_elevation_m=float(np.mean(elevations)), elevation_range_m=float(np.ptp(elevations)),
                              elevation_stddev_m_roughness_proxy=float(np.std(elevations)))
                region.update(mean_slope_deg=float(np.mean(slopes)), maximum_slope_deg=float(np.max(slopes)))
            else:
                result["warnings"].append("No pixels with both valid elevation and slope occur in the analysis region.")
            if len(elevations) < inside:
                result["warnings"].append("Some pixels in the in-raster analysis circle have missing or invalid source data.")
            return result
