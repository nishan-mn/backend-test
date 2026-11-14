from pathlib import Path

import pytest

from app.models import AnalysisRequest


def pytest_addoption(parser):
    parser.addoption("--live-horizons", action="store_true", help="Enable real NASA requests")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--live-horizons"):
        for item in items:
            if "live" in item.keywords:
                item.add_marker(pytest.mark.skip(reason="Use --live-horizons to enable NASA requests"))


@pytest.fixture(autouse=True)
def offline_application_contact(request, monkeypatch):
    if "live" not in request.keywords:
        # Reserved test address, used only with simulated NASA transports, never live tests.
        monkeypatch.setenv("LUNAR_COMPASS_CONTACT", "offline-tests@example.invalid")


@pytest.fixture
def payload():
    return dict(latitude_deg=-85.2, longitude_deg=32.5, start_utc="2026-11-20T00:00:00Z", duration_hours=1)


@pytest.fixture
def mission(payload):
    return AnalysisRequest(**payload)


@pytest.fixture
def reports():
    # Unmodified real NASA reports captured on 2026-11-13. Never used by production code.
    return {
        target: Path(__file__).with_name("fixtures").joinpath(f"horizons_{target}.txt").read_text(encoding="utf-8")
        for target in (10, 399)
    }


@pytest.fixture
def six_day_reports():
    return {
        target: Path(__file__).with_name("fixtures").joinpath(f"horizons_{target}_144h.txt").read_text(encoding="utf-8")
        for target in (10, 399)
    }
