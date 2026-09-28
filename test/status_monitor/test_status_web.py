from unittest.mock import patch

import pytest

# status_web mounts the React build directory at import time, which only exists in the built
# image, so stub out StaticFiles to import the pure helpers under test.
with patch("fastapi.staticfiles.StaticFiles"):
    from app.status_monitor.status_web import cloud_dashboard_url, get_cloud_config


@pytest.mark.parametrize(
    "cloud_endpoint, expected_dashboard_url",
    [
        ("https://api.groundlight.ai/device-api", "https://dashboard.groundlight.ai"),
        ("https://api.integ.groundlight.ai/device-api", "https://dashboard.integ.groundlight.ai"),
        ("https://api.dev.groundlight.ai/device-api", "https://dashboard.dev.groundlight.ai"),
        ("https://api.groundlight.dev.axon.com/device-api", "https://dashboard.groundlight.dev.axon.com"),
        ("https://api.groundlight.usa.axon.com/device-api", "https://dashboard.groundlight.usa.axon.com"),
    ],
)
def test_cloud_dashboard_url_swaps_api_for_dashboard(
    monkeypatch: pytest.MonkeyPatch, cloud_endpoint: str, expected_dashboard_url: str
):
    """The dashboard URL is derived from the cloud endpoint by swapping the leading 'api.' host label."""
    monkeypatch.setenv("GROUNDLIGHT_ENDPOINT", cloud_endpoint)
    assert cloud_dashboard_url() == expected_dashboard_url


def test_cloud_config_reports_upstream_and_dashboard(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GROUNDLIGHT_ENDPOINT", "https://api.groundlight.dev.axon.com/device-api/")
    assert get_cloud_config() == {
        "upstream_endpoint": "https://api.groundlight.dev.axon.com",
        "dashboard_url": "https://dashboard.groundlight.dev.axon.com",
    }
