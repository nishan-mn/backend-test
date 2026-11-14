"""Dataset-backed retrieval functions for the Historical Mission Explorer."""

from __future__ import annotations

from typing import Any

from app.data.historical_missions import MISSIONS, SOURCES, get_mission
from app.models import (
    HistoricalReplayInput,
    MissionDetail,
    MissionSummary,
    ReplayRequest,
    SourceCitation,
)


def _normalise_filter(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    normalised = value.strip().casefold()
    if not normalised:
        raise ValueError(f"{field_name} cannot be empty")
    return normalised


def _sources_for(mission: dict[str, Any]) -> list[SourceCitation]:
    citations: list[SourceCitation] = []
    for source_key in mission["source_keys"]:
        source = SOURCES.get(source_key)
        if source is None:
            raise ValueError(
                f"Mission '{mission['id']}' references unknown source '{source_key}'"
            )
        citations.append(SourceCitation(key=source_key, **source))
    return citations


def _summary_from(mission: dict[str, Any]) -> MissionSummary:
    actual_location = mission["actual_location"]
    return MissionSummary(
        id=mission["id"],
        name=mission["name"],
        country=mission["country"],
        operator=mission["operator"],
        event_time_utc=mission["event_time_utc"],
        time_precision=mission["time_precision"],
        landing_outcome=mission["landing_outcome"],
        marker_location={
            "latitude_deg": actual_location["latitude_deg"],
            "longitude_deg": actual_location["longitude_deg"],
            "location_type": actual_location["location_type"],
            "coordinate_quality": actual_location["coordinate_quality"],
        },
        replay=mission["replay"],
    )


def list_mission_summaries(
    *, country: str | None = None, landing_outcome: str | None = None
) -> list[MissionSummary]:
    """Return mission cards, optionally filtered by country or landing outcome."""

    country_filter = _normalise_filter(country, "country")
    outcome_filter = _normalise_filter(landing_outcome, "landing_outcome")
    summaries = []
    for mission in MISSIONS:
        if country_filter is not None and mission["country"].casefold() != country_filter:
            continue
        if outcome_filter is not None and mission["landing_outcome"].casefold() != outcome_filter:
            continue
        summaries.append(_summary_from(mission))
    return summaries


def get_mission_detail(mission_id: str) -> MissionDetail | None:
    """Return one complete mission record and its source provenance, if it exists."""

    if not mission_id or not mission_id.strip():
        raise ValueError("mission_id cannot be empty")
    mission = get_mission(mission_id)
    if mission is None:
        return None
    mission_payload = {field: value for field, value in mission.items() if field != "source_keys"}
    return MissionDetail(**mission_payload, sources=_sources_for(mission))


def get_replay_input(
    mission_id: str, request: ReplayRequest | None = None
) -> HistoricalReplayInput | None:
    """Return historical inputs for the shared visibility engine when replay is allowed."""

    detail = get_mission_detail(mission_id)
    if detail is None or not detail.replay.status.startswith("eligible"):
        return None
    selected_location = getattr(detail, detail.replay.location_field)
    replay_request = request or ReplayRequest()
    return HistoricalReplayInput(
        latitude_deg=selected_location.latitude_deg,
        longitude_deg=selected_location.longitude_deg,
        start_utc=detail.event_time_utc,
        duration_hours=replay_request.duration_hours,
        historical_context={
            "mission_id": detail.id,
            "location_label": detail.replay.label,
            "location_type": selected_location.location_type,
            "coordinate_quality": selected_location.coordinate_quality,
        },
    )


def validate_historical_dataset() -> None:
    """Validate all local records and source references."""

    mission_ids: set[str] = set()
    for mission in MISSIONS:
        mission_id = mission.get("id")
        if mission_id in mission_ids:
            raise ValueError(f"Duplicate mission id '{mission_id}'")
        mission_ids.add(mission_id)
        if get_mission_detail(mission_id) is None:
            raise ValueError(f"Mission '{mission_id}' could not be retrieved")
        if mission["replay"]["status"].startswith("eligible"):
            get_replay_input(mission_id)
