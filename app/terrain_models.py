from pydantic import BaseModel, ConfigDict, Field

class TerrainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    latitude_deg: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude_deg: float = Field(allow_inf_nan=False)
    analysis_radius_m: float = Field(default=500, gt=0, allow_inf_nan=False)

class Location(BaseModel):
    latitude_deg: float
    longitude_deg: float

class PixelMetrics(BaseModel):
    row: int | None
    column: int | None
    elevation_m: float | None
    slope_deg: float | None

class RegionMetrics(BaseModel):
    analysis_radius_m: float
    mean_elevation_m: float | None
    elevation_range_m: float | None
    mean_slope_deg: float | None
    maximum_slope_deg: float | None
    elevation_stddev_m_roughness_proxy: float | None
    valid_pixel_count: int
    total_pixel_count: int
    valid_pixel_percentage: float
    valid_data_percentage: float
    requested_area_coverage_percentage: float
    coverage_status: str

class RasterInfo(BaseModel):
    resolution_m: float
    crs: str
    dataset_provenance: str
    dataset_source_url: str
    dataset_limitations: list[str]

class TerrainResponse(BaseModel):
    terrain_available: bool
    location: Location
    pixel: PixelMetrics
    region: RegionMetrics
    raster: RasterInfo
    warnings: list[str]
