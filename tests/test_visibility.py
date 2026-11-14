from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.models import AnalysisRequest
from app.services.horizons import Ephemeris, HorizonsError, Position
from app.services.metrics import calculate_metrics
from app.services.visibility import assemble_analysis, midpoint_samples


@pytest.mark.parametrize("duration", [1, 2, 144, 336])
def test_exact_midpoint_series(payload, duration):
    mission = AnalysisRequest(**(payload | {"duration_hours": duration}))
    samples = midpoint_samples(mission)
    assert len(samples) == duration
    assert samples[0] == datetime(2026, 11, 20, 0, 30, tzinfo=UTC)
    assert samples[-1] == mission.start_utc + timedelta(hours=duration, minutes=-30)
    assert all(right - left == timedelta(hours=1) for left, right in zip(samples, samples[1:]))
    if duration == 144:
        assert samples[-1] == datetime(2026, 11, 25, 23, 30, tzinfo=UTC)


@pytest.mark.parametrize("sun,earth,expected", [
    ([True] * 4, [True] * 4, (100, 100, 0, 0)),
    ([False] * 4, [False] * 4, (0, 0, 4, 4)),
    ([True, False] * 2, [False, True] * 2, (50, 50, 1, 1)),
    ([False, False, True, False], [True, False, False, False], (25, 25, 2, 3)),
    ([True, True, False, False], [False, False, False, True], (50, 25, 2, 3)),
    ([True] * 90 + [False] * 54, [False] * 36 + [True] * 108, (62.5, 75, 54, 36)),
])
def test_metrics(sun, earth, expected):
    result = calculate_metrics(sun, earth)
    assert tuple(result.model_dump().values()) == expected


@pytest.mark.parametrize("sun,earth", [([], []), ([True], []), ([None], [False]), ([1], [False])])
def test_metrics_refuse_missing_data(sun, earth):
    with pytest.raises(ValueError):
        calculate_metrics(sun, earth)


def series(mission, elevations):
    return Ephemeris(
        tuple(Position(t, 45.0, elevation) for t, elevation in zip(midpoint_samples(mission), elevations)),
        "MEAN_ME (high precision)", (1737.4, 1737.4, 1737.4),
    )


def test_elevation_signs_and_intervals(payload):
    mission = AnalysisRequest(**(payload | {"longitude_deg": -30, "duration_hours": 3}))
    result = assemble_analysis(mission, series(mission, [0.1, 0.0, -0.1]), series(mission, [-0.1, 0, 0.1]))
    assert [row.sun_visible for row in result.timeline] == [True, False, False]
    assert [row.earth_visible for row in result.timeline] == [False, False, True]
    assert result.metrics.sunlight_percent == pytest.approx(100 / 3)
    assert result.metrics.longest_darkness_hours == 2
    assert result.metrics.longest_earth_gap_hours == 2
    assert result.location.longitude_deg == -30
    assert result.timeline[0].interval_start_utc == mission.start_utc
    assert result.timeline[-1].interval_end_utc == result.end_utc
    assert result.end_utc == mission.start_utc + timedelta(hours=3)


@pytest.mark.parametrize("problem", ["missing", "shifted", "reordered", "frame", "radii"])
def test_alignment_failure(payload, problem):
    mission = AnalysisRequest(**(payload | {"duration_hours": 2}))
    sun = series(mission, [1, 1])
    earth = series(mission, [2, 2])
    if problem == "missing":
        earth = replace(earth, positions=earth.positions[:1])
    elif problem == "shifted":
        earth = replace(earth, positions=tuple(replace(p, timestamp=p.timestamp + timedelta(seconds=1)) for p in earth.positions))
    elif problem == "reordered":
        earth = replace(earth, positions=earth.positions[::-1])
    elif problem == "frame":
        earth = replace(earth, reference_frame="unexpected")
    else:
        earth = replace(earth, radii_km=(1, 1, 1))
    with pytest.raises(HorizonsError):
        assemble_analysis(mission, sun, earth)
