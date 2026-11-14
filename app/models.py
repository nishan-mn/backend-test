"""Public API contract; coordinates are lunar, east-positive degrees."""

import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

Latitude = Annotated[float, Field(strict=True, ge=-90, le=90, allow_inf_nan=False)]
Longitude = Annotated[float, Field(strict=True, ge=-180, le=180, allow_inf_nan=False)]
Elevation = Latitude
Azimuth = Annotated[float, Field(ge=0, le=360, allow_inf_nan=False)]
Hours = Annotated[int, Field(strict=True, ge=1, le=336)]
Percent = Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude_deg: Latitude
    longitude_deg: Longitude
    start_utc: datetime
    duration_hours: Hours

    @field_validator("start_utc", mode="before")
    @classmethod
    def require_utc(cls, value: object) -> datetime:
        if isinstance(value, str):
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", value):
                raise ValueError("Use an ISO 8601 UTC timestamp ending in Z or +00:00")
            value = datetime.fromisoformat(value)
        if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
            raise ValueError("start_utc must have an explicit UTC timezone")
        if value.microsecond % 1000:
            raise ValueError("start_utc must use millisecond precision or coarser (Horizons output precision)")
        if value.year < 1962:
            raise ValueError("start_utc must be in 1962 or later; earlier Horizons UT dates are UT1, not UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def check_end_time(self) -> "AnalysisRequest":
        try:
            self.start_utc + timedelta(hours=self.duration_hours)
        except OverflowError as exc:
            raise ValueError("Mission end exceeds the supported datetime range") from exc
        return self


class Location(BaseModel):
    latitude_deg: Latitude
    longitude_deg: Longitude


class Metrics(BaseModel):
    sunlight_percent: Percent
    earth_visibility_percent: Percent
    longest_darkness_hours: Annotated[int, Field(ge=0, le=336)]
    longest_earth_gap_hours: Annotated[int, Field(ge=0, le=336)]


class TimelineEntry(BaseModel):
    interval_start_utc: datetime
    interval_end_utc: datetime
    sample_utc: datetime
    sun_azimuth_deg: Azimuth
    sun_elevation_deg: Elevation
    earth_azimuth_deg: Azimuth
    earth_elevation_deg: Elevation
    sun_visible: bool
    earth_visible: bool


class ModelMetadata(BaseModel):
    type: Literal["simplified_geometric_horizon"] = "simplified_geometric_horizon"
    horizon_degrees: Literal[0] = 0
    site_altitude_km: Literal[0] = 0
    terrain_obstruction_included: Literal[False] = False
    sampling_method: Literal["hourly_midpoints"] = "hourly_midpoints"
    source: Literal["NASA JPL Horizons"] = "NASA JPL Horizons"
    lunar_reference_frame: str
    lunar_radii_km: tuple[float, float, float]
    limitations: tuple[str, ...] = (
        "Body centers above a zero-degree local horizon; apparent airless angles.",
        "Altitude 0 km on the Horizons lunar reference ellipsoid is an approximation.",
        "Hourly midpoint estimates, not exact rise/set times; gaps are clipped to the mission.",
        "No terrain obstruction, finite body discs, or eclipse/occultation screening.",
        "Visibility does not guarantee usable solar power, communication, or landing safety.",
    )


class AnalysisResponse(BaseModel):
    location: Location
    start_utc: datetime
    end_utc: datetime
    duration_hours: Hours
    sampling_minutes: Literal[60] = 60
    metrics: Metrics
    timeline: Annotated[list[TimelineEntry], Field(min_length=1, max_length=336)]
    model: ModelMetadata


HistoricalLatitude = Annotated[float, Field(strict=True, ge=-90, le=90, allow_inf_nan=False)]
HistoricalLongitude = Annotated[float, Field(strict=True, ge=0, lt=360, allow_inf_nan=False)]


class HistoricalModel(BaseModel):
    """Base contract for source-backed historical mission records."""

    model_config = ConfigDict(extra="forbid")


class SourceCitation(HistoricalModel):
    key: Annotated[str, Field(min_length=1)]
    title: Annotated[str, Field(min_length=1)]
    url: HttpUrl
    supports: Annotated[str, Field(min_length=1)]


class MissionLocation(HistoricalModel):
    name: Annotated[str, Field(min_length=1)]
    latitude_deg: HistoricalLatitude
    longitude_deg: HistoricalLongitude
    location_type: Annotated[str, Field(min_length=1)]
    coordinate_quality: Annotated[str, Field(min_length=1)]
    precision_or_uncertainty: Annotated[str, Field(min_length=1)]
    coordinate_reference: Annotated[str, Field(min_length=1)]
    original_coordinate_text: Annotated[str, Field(min_length=1)]
    source_keys: Annotated[list[str], Field(min_length=1)]


class MissionMarkerLocation(HistoricalModel):
    latitude_deg: HistoricalLatitude
    longitude_deg: HistoricalLongitude
    location_type: Annotated[str, Field(min_length=1)]
    coordinate_quality: Annotated[str, Field(min_length=1)]


class ReplayMetadata(HistoricalModel):
    status: Literal["eligible", "eligible_with_location_note", "ineligible"]
    location_field: Literal["actual_location", "intended_location"]
    label: Annotated[str, Field(min_length=1)]


class MissionSummary(HistoricalModel):
    id: Annotated[str, Field(min_length=1)]
    name: Annotated[str, Field(min_length=1)]
    country: Annotated[str, Field(min_length=1)]
    operator: Annotated[str, Field(min_length=1)]
    event_time_utc: datetime
    time_precision: Annotated[str, Field(min_length=1)]
    landing_outcome: Annotated[str, Field(min_length=1)]
    marker_location: MissionMarkerLocation
    replay: ReplayMetadata

    @field_validator("event_time_utc")
    @classmethod
    def event_time_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("event_time_utc must be a UTC timestamp")
        return value


class MissionDetail(HistoricalModel):
    id: Annotated[str, Field(min_length=1)]
    name: Annotated[str, Field(min_length=1)]
    spacecraft_or_lander: Annotated[str, Field(min_length=1)]
    country: Annotated[str, Field(min_length=1)]
    operator: Annotated[str, Field(min_length=1)]
    event_time_utc: datetime
    time_precision: Annotated[str, Field(min_length=1)]
    event_description: Annotated[str, Field(min_length=1)]
    mission_objective: Annotated[str, Field(min_length=1)]
    landing_outcome: Annotated[str, Field(min_length=1)]
    overall_mission_outcome: Annotated[str, Field(min_length=1)]
    documented_failure_reason: str | None = None
    what_happened: Annotated[str, Field(min_length=1)]
    achievements: Annotated[str, Field(min_length=1)]
    intended_location: MissionLocation
    actual_location: MissionLocation
    replay: ReplayMetadata
    media: list[dict[str, Any]] = Field(default_factory=list)
    sources: Annotated[list[SourceCitation], Field(min_length=1)]

    @field_validator("event_time_utc")
    @classmethod
    def event_time_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("event_time_utc must be a UTC timestamp")
        return value


class ReplayRequest(HistoricalModel):
    duration_hours: Hours = 144


class ReplayHistoricalContext(HistoricalModel):
    mission_id: Annotated[str, Field(min_length=1)]
    location_label: Annotated[str, Field(min_length=1)]
    location_type: Annotated[str, Field(min_length=1)]
    coordinate_quality: Annotated[str, Field(min_length=1)]


class HistoricalReplayInput(HistoricalModel):
    latitude_deg: HistoricalLatitude
    longitude_deg: HistoricalLongitude
    start_utc: datetime
    duration_hours: Hours
    historical_context: ReplayHistoricalContext

    @field_validator("start_utc")
    @classmethod
    def start_time_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("start_utc must be a UTC timestamp")
        return value


class ErrorResponse(HistoricalModel):
    """Error payload matching the existing API's ``detail`` convention."""

    detail: Annotated[str, Field(min_length=1)]
