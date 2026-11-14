import json

import httpx
import pytest
from fastapi.testclient import TestClient
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.main import create_app, get_http_client
from app.models import AnalysisRequest, AnalysisResponse


@pytest.fixture
def client(reports):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, text=reports[int(request.url.params["COMMAND"].strip("'"))])

    app = create_app()
    with TestClient(app) as client:
        mock_http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        app.dependency_overrides[get_http_client] = lambda: mock_http
        client.horizons_calls = calls
        yield client


def test_health_never_calls_nasa(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.horizons_calls == []


def test_complete_real_fixture_response(client, payload):
    response = client.post("/api/analyze", json=payload)
    assert response.status_code == 200
    data = response.json()
    parsed = AnalysisResponse.model_validate(data)
    assert len(parsed.timeline) == 1
    assert data["start_utc"] == "2026-11-20T00:00:00Z"
    assert data["end_utc"] == "2026-11-20T01:00:00Z"
    assert data["metrics"] == dict(sunlight_percent=100, earth_visibility_percent=100, longest_darkness_hours=0, longest_earth_gap_hours=0)
    assert data["timeline"][0]["sun_elevation_deg"] == 6.029127
    assert data["timeline"][0]["earth_elevation_deg"] == 6.884094
    assert data["model"]["terrain_obstruction_included"] is False
    assert len(client.horizons_calls) == 2
    data["timeline"][0]["sun_elevation_deg"] = None
    with pytest.raises(ValidationError):
        AnalysisResponse.model_validate(data)


def test_six_day_api_has_exactly_two_requests(client, payload, reports, six_day_reports):
    reports.update(six_day_reports)
    response = client.post("/api/analyze", json=payload | {"duration_hours": 144})
    assert response.status_code == 200
    data = response.json()
    assert len(data["timeline"]) == 144
    assert data["timeline"][0]["sample_utc"] == "2026-11-20T00:30:00Z"
    assert data["timeline"][-1]["sample_utc"] == "2026-11-25T23:30:00Z"
    assert data["end_utc"] == "2026-11-26T00:00:00Z"
    assert len(client.horizons_calls) == 2


@pytest.mark.parametrize("field,value", [
    ("latitude_deg", -90.1), ("latitude_deg", 90.1), ("latitude_deg", True),
    ("latitude_deg", "20"), ("longitude_deg", -180.1), ("longitude_deg", 180.1),
    ("longitude_deg", False), ("longitude_deg", "nan"),
    ("duration_hours", 0), ("duration_hours", -1), ("duration_hours", 337),
    ("duration_hours", 1.5), ("duration_hours", 1.0), ("duration_hours", True),
    ("duration_hours", "144"), ("duration_hours", None),
    ("start_utc", "2026-11-20T00:00:00"), ("start_utc", "2026-11-20"),
    ("start_utc", "2026-11-20T05:30:00+05:30"), ("start_utc", "2026-11-20T00:00:00-00:00"),
    ("start_utc", "2026-02-30T00:00:00Z"), ("start_utc", "invalid"),
    ("start_utc", 1795132800), ("start_utc", "2026-11-20T00:00:00.123456Z"),
    ("start_utc", "1961-11-20T00:00:00Z"), ("start_utc", "9999-12-31T23:30:00Z"),
    ("unexpected", 1),
])
def test_invalid_input_is_422(client, payload, field, value):
    response = client.post("/api/analyze", json=payload | {field: value})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert client.horizons_calls == []


@pytest.mark.parametrize("field", ["latitude_deg", "longitude_deg", "start_utc", "duration_hours"])
def test_missing_fields(client, payload, field):
    del payload[field]
    assert client.post("/api/analyze", json=payload).status_code == 422


@pytest.mark.parametrize("field", ["latitude_deg", "longitude_deg", "duration_hours"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_input_is_422(client, payload, field, value):
    response = client.post("/api/analyze", content=json.dumps(payload | {field: value}), headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert client.horizons_calls == []


@pytest.mark.parametrize("field,value", [
    ("start_utc", "\ud800"), ("start_utc", "\udfff"),
    ("\ud800", "private input"), ("\udfff", {"\ud800": b"not serialized".hex()}),
    ("duration_hours", {"\ud800": float("nan")}),
])
def test_unsafe_json_inputs_have_safe_validation_errors(client, payload, field, value):
    response = client.post("/api/analyze", content=json.dumps(payload | {field: value}),
                           headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    response.content.decode("utf-8", errors="strict")
    errors = response.json()["detail"]
    assert isinstance(errors, list) and errors
    for error in errors:
        assert set(error) == {"type", "loc", "msg"}
        json.dumps(error, ensure_ascii=False).encode("utf-8", errors="strict")
    assert "private input" not in response.text
    assert client.horizons_calls == []


def test_invalid_text_bytes_have_safe_validation_error(client):
    response = client.post("/api/analyze", content=b"\xff", headers={"Content-Type": "text/plain"})
    assert response.status_code == 422
    error = response.json()["detail"][0]
    assert error["loc"] == ["body"]
    assert set(error) == {"type", "loc", "msg"}
    assert client.horizons_calls == []


def test_unsafe_error_locations_and_messages():
    app = create_app()

    @app.get("/test-validation")
    async def invalid():
        raise RequestValidationError([{
            "type": b"invalid_\xff", "loc": ("body", "\ud800", b"\xff", 2),
            "msg": "Invalid \udfff", "input": b"private input",
            "ctx": {"error": ValueError("private context")},
        }])

    with TestClient(app) as client:
        response = client.get("/test-validation")
    assert response.status_code == 422
    assert response.json() == {"detail": [{
        "type": "invalid_\\xff", "loc": ["body", "\\ud800", "\\xff", 2], "msg": "Invalid \\udfff",
    }]}
    assert "private" not in response.text


def test_normal_validation_metadata_is_preserved(client, payload):
    response = client.post("/api/analyze", json=payload | {"duration_hours": 0})
    assert response.status_code == 422
    assert response.json()["detail"] == [{
        "type": "greater_than_equal", "loc": ["body", "duration_hours"],
        "msg": "Input should be greater than or equal to 1",
    }]


def test_unrelated_programming_errors_are_not_client_errors(monkeypatch, payload):
    async def broken(*args):
        raise RuntimeError("programming error")

    monkeypatch.setattr("app.main.analyze_visibility", broken)
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        response = client.post("/api/analyze", json=payload)
    assert response.status_code == 500
    assert "programming error" not in response.text


def test_missing_application_contact_returns_503(client, payload, monkeypatch):
    monkeypatch.delenv("LUNAR_COMPASS_CONTACT", raising=False)
    response = client.post("/api/analyze", json=payload)
    assert response.status_code == 503
    assert "LUNAR_COMPASS_CONTACT" in response.json()["detail"]
    assert client.horizons_calls == []


@pytest.mark.parametrize("latitude,longitude", [(-90, -180), (90, 180), (0, 0), (-85.2, 32.5)])
def test_valid_coordinate_boundaries(payload, latitude, longitude):
    result = AnalysisRequest(**(payload | {"latitude_deg": latitude, "longitude_deg": longitude}))
    assert result.latitude_deg == latitude
    assert result.longitude_deg == longitude


@pytest.mark.parametrize("start", ["2026-11-20T00:00:00Z", "2026-11-20T00:00:00+00:00", "2026-11-20T00:00:00.000Z", "2026-11-20T00:00:00.123Z"])
def test_valid_utc(payload, start):
    assert AnalysisRequest(**(payload | {"start_utc": start})).start_utc.utcoffset().total_seconds() == 0


@pytest.mark.parametrize("failure,status", [(httpx.ReadTimeout, 504), (httpx.ConnectError, 503), (500, 502), ("scientific error", 502)])
def test_api_upstream_errors(payload, failure, status):
    def handler(request):
        if isinstance(failure, type):
            raise failure("private details", request=request)
        return httpx.Response(failure if isinstance(failure, int) else 200, text="private details")

    app = create_app()
    with TestClient(app) as client:
        app.dependency_overrides[get_http_client] = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
        response = client.post("/api/analyze", json=payload)
    assert response.status_code == status
    assert set(response.json()) == {"detail"}
    assert "private" not in response.text
    assert "Traceback" not in response.text


def test_cors_allowlist(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://frontend.example")
    with TestClient(create_app()) as client:
        headers = {"Origin": "https://frontend.example", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "Content-Type"}
        allowed = client.options("/api/analyze", headers=headers)
        assert allowed.status_code == 200
        assert allowed.headers["access-control-allow-origin"] == "https://frontend.example"
        blocked = client.options("/api/analyze", headers=headers | {"Origin": "https://other.example"})
        assert "access-control-allow-origin" not in blocked.headers
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")
    with pytest.raises(ValueError, match="wildcards"):
        create_app()
