"""Four estimates over equally weighted, one-hour intervals."""

from collections.abc import Sequence

from app.models import Metrics


def _longest_gap(visible: Sequence[bool]) -> int:
    longest = current = 0
    for value in visible:
        current = 0 if value else current + 1
        longest = max(longest, current)
    return longest


def calculate_metrics(sun_visible: Sequence[bool], earth_visible: Sequence[bool]) -> Metrics:
    if not sun_visible or len(sun_visible) != len(earth_visible):
        raise ValueError("Metrics require nonempty, aligned visibility series")
    if any(type(value) is not bool for series in (sun_visible, earth_visible) for value in series):
        raise ValueError("Missing or invalid visibility values cannot be treated as invisible")
    return Metrics(
        sunlight_percent=100 * sum(sun_visible) / len(sun_visible),
        earth_visibility_percent=100 * sum(earth_visible) / len(earth_visible),
        longest_darkness_hours=_longest_gap(sun_visible),
        longest_earth_gap_hours=_longest_gap(earth_visible),
    )
