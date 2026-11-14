"""Reusable lunar visibility calculation, independent of FastAPI."""

from datetime import datetime, timedelta

import httpx

from app.models import AnalysisRequest, AnalysisResponse, Location, ModelMetadata, TimelineEntry
from app.services.horizons import Ephemeris, HorizonsClient, HorizonsError, TIMEOUT
from app.services.metrics import calculate_metrics


def midpoint_samples(request: AnalysisRequest) -> list[datetime]:
    return [request.start_utc + timedelta(hours=hour, minutes=30) for hour in range(request.duration_hours)]


def assemble_analysis(request: AnalysisRequest, sun: Ephemeris, earth: Ephemeris) -> AnalysisResponse:
    expected = midpoint_samples(request)
    for series in (sun, earth):
        if [position.timestamp for position in series.positions] != expected:
            raise HorizonsError("Sun and Earth samples must exactly match the mission midpoint timestamps")
    if sun.reference_frame != earth.reference_frame or sun.radii_km != earth.radii_km:
        raise HorizonsError("Sun and Earth ephemerides use inconsistent lunar reference models")
    timeline = [
        TimelineEntry(
            interval_start_utc=sample - timedelta(minutes=30),
            interval_end_utc=sample + timedelta(minutes=30),
            sample_utc=sample,
            sun_azimuth_deg=sun_position.azimuth_deg,
            sun_elevation_deg=sun_position.elevation_deg,
            earth_azimuth_deg=earth_position.azimuth_deg,
            earth_elevation_deg=earth_position.elevation_deg,
            sun_visible=sun_position.elevation_deg > 0,
            earth_visible=earth_position.elevation_deg > 0,
        )
        for sample, sun_position, earth_position in zip(expected, sun.positions, earth.positions, strict=True)
    ]
    return AnalysisResponse(
        location=Location(latitude_deg=request.latitude_deg, longitude_deg=request.longitude_deg),
        start_utc=request.start_utc,
        end_utc=request.start_utc + timedelta(hours=request.duration_hours),
        duration_hours=request.duration_hours,
        metrics=calculate_metrics(
            [row.sun_visible for row in timeline], [row.earth_visible for row in timeline]
        ),
        timeline=timeline,
        model=ModelMetadata(lunar_reference_frame=sun.reference_frame, lunar_radii_km=sun.radii_km),
    )


async def analyze_visibility(
    request: AnalysisRequest, http_client: httpx.AsyncClient | None = None
) -> AnalysisResponse:
    """Fetch two complete NASA series. Raises HorizonsError on any upstream failure."""
    if http_client is None:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            return await analyze_visibility(request, client)
    horizons = HorizonsClient(http_client)
    samples = midpoint_samples(request)
    sun = await horizons.get_series(10, request, samples)
    earth = await horizons.get_series(399, request, samples)
    return assemble_analysis(request, sun, earth)
