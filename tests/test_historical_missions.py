"""Tests for source-backed Historical Mission Explorer records."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.data.historical_missions import MISSIONS, SOURCES
from app.main import create_app
from app.services.historical_missions import (
    get_mission_detail,
    get_replay_input,
    list_mission_summaries,
    validate_historical_dataset,
)


def test_all_historical_records_validate_with_sources_and_coordinates():
    validate_historical_dataset()
    assert len(MISSIONS) == 6

    for raw_mission in MISSIONS:
        mission = get_mission_detail(raw_mission["id"])
        assert mission is not None
        assert mission.event_time_utc.utcoffset() == timedelta(0)
        assert -90 <= mission.actual_location.latitude_deg <= 90
        assert 0 <= mission.actual_location.longitude_deg < 360
        assert [source.key for source in mission.sources] == raw_mission["source_keys"]
        assert all(source.key in SOURCES for source in mission.sources)


def test_history_is_separate_from_modeled_replay_output():
    mission = get_mission_detail("chandrayaan_3")
    assert mission is not None
    payload = mission.model_dump(mode="json")
    assert "sources" in payload
    assert "replay" in payload
    assert "timeline" not in payload
    assert "metrics" not in payload

    replay_input = get_replay_input("chandrayaan_3")
    assert replay_input is not None
    assert replay_input.historical_context.mission_id == mission.id
    assert replay_input.latitude_deg == mission.actual_location.latitude_deg
    assert replay_input.longitude_deg == mission.actual_location.longitude_deg


def test_service_filters_and_invalid_inputs():
    assert len(list_mission_summaries(country="India")) == 2
    assert len(list_mission_summaries(landing_outcome="successful_soft_landing")) == 3
    assert list_mission_summaries(country="Japan") == []
    assert get_mission_detail("unknown") is None

    with pytest.raises(ValueError, match="country cannot be empty"):
        list_mission_summaries(country="  ")
    with pytest.raises(ValueError, match="mission_id cannot be empty"):
        get_mission_detail(" ")


def test_mission_routes_return_history_without_calling_horizons():
    with TestClient(create_app()) as client:
        response = client.get("/api/missions")
        assert response.status_code == 200
        missions = response.json()
        assert len(missions) == 6
        assert "intended_location" not in missions[0]

        response = client.get("/api/missions", params={"country": "India"})
        assert response.status_code == 200
        assert [mission["id"] for mission in response.json()] == [
            "chandrayaan_3",
            "chandrayaan_2_vikram",
        ]

        response = client.get("/api/missions/chandrayaan_3")
        assert response.status_code == 200
        detail = response.json()
        assert detail["actual_location"]["latitude_deg"] == -69.3741
        assert [source["key"] for source in detail["sources"]] == ["CY3-1", "CY3-2", "CY3-3"]


def test_mission_route_failures_are_clear():
    with TestClient(create_app()) as client:
        missing = client.get("/api/missions/not-a-mission")
        assert missing.status_code == 404
        assert missing.json() == {"detail": "Mission not found"}

        invalid = client.get("/api/missions", params={"country": "  "})
        assert invalid.status_code == 422
        assert invalid.json() == {"detail": "country cannot be empty"}
