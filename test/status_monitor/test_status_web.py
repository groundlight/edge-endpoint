from unittest.mock import Mock, patch

import pytest

# status_web mounts the React build directory at import time, which only exists in the built
# image, so stub out StaticFiles to import the pure cloud_dashboard_url() helper under test.
with patch("fastapi.staticfiles.StaticFiles"):
    from app.status_monitor.status_web import cloud_dashboard_url


@pytest.mark.parametrize(
    "cloud_endpoint, expected_dashboard_url",
    [
        ("https://api.groundlight.ai/device-api", "https://dashboard.groundlight.ai"),
        ("https://api.integ.groundlight.ai/device-api", "https://dashboard.integ.groundlight.ai"),
        ("https://api.dev.groundlight.ai/device-api", "https://dashboard.dev.groundlight.ai"),
        ("https://api.groundlight.dev.axon.com/device-api", "https://dashboard.groundlight.dev.axon.com"),
        ("https://api.groundlight.us1.axon.com/device-api", "https://dashboard.groundlight.us1.axon.com"),
    ],
)
def test_cloud_dashboard_url_swaps_api_for_dashboard(cloud_endpoint, expected_dashboard_url):
    """The dashboard URL is derived from the cloud endpoint by swapping the leading 'api.' host label."""
    with patch("app.status_monitor.status_web.groundlight_client", return_value=Mock(endpoint=cloud_endpoint)):
        assert cloud_dashboard_url() == expected_dashboard_url
