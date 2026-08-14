"""HTTP-level tests that router auth gating is wired correctly."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from app.api.api import HEALTH, IMAGE_QUERIES, PING
from app.api.naming import full_path, path_prefix
from app.escalation_queue.queue_writer import QueueWriter
from app.main import app
from app.metrics.iq_activity import FilesystemActivityTrackingHelper


@pytest.fixture(scope="module")
def enforcing_auth_client(tmp_path_factory) -> TestClient:
    """TestClient where missing x-api-token is rejected on gated routes."""

    def mock_get_database_url():
        return "sqlite:///:memory:"

    def validate_request(request):
        if not request.headers.get("x-api-token"):
            raise HTTPException(status_code=401, detail="Missing x-api-token header.")

    mock_auth = MagicMock()
    mock_auth.validate_request.side_effect = validate_request
    queue_dir = tmp_path_factory.mktemp("escalation_queue_auth")
    metrics_dir = tmp_path_factory.mktemp("edge-metrics_auth")
    active_config_path = tmp_path_factory.mktemp("edge_config_auth") / "active-edge-config.yaml"
    metrics_tracker = FilesystemActivityTrackingHelper(base_dir=str(metrics_dir))

    with (
        patch("app.core.database.get_database_url", mock_get_database_url),
        patch("app.main.edge_endpoint_auth_manager", return_value=mock_auth),
        patch("app.core.edge_endpoint_auth.edge_endpoint_auth_manager", return_value=mock_auth),
        patch("app.core.app_state.QueueWriter", lambda: QueueWriter(base_dir=str(queue_dir))),
        patch("app.core.edge_config_manager.ACTIVE_EDGE_CONFIG_PATH", str(active_config_path)),
        patch("app.main.ACTIVE_EDGE_CONFIG_PATH", str(active_config_path)),
        patch("app.metrics.iq_activity._tracker", return_value=metrics_tracker),
    ):
        with TestClient(app) as client:
            yield client


@pytest.mark.parametrize(
    "method,url,kwargs",
    [
        ("get", "/edge-config", {}),
        ("put", "/edge-config", {"json": {}}),
        ("get", "/edge-detector-readiness", {}),
        ("post", full_path(IMAGE_QUERIES), {"params": {"detector_id": "det_AAAAAAAAAAAAAAAAAAAAAAAAAAA"}}),
    ],
)
def test_gated_routes_require_api_token(enforcing_auth_client: TestClient, method, url, kwargs):
    response = getattr(enforcing_auth_client, method)(url, **kwargs)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["detail"] == "Missing x-api-token header."


def test_health_and_ping_remain_ungated(enforcing_auth_client: TestClient):
    live = enforcing_auth_client.get(path_prefix(HEALTH) + "/live")
    assert live.status_code == status.HTTP_200_OK

    ready = enforcing_auth_client.get(path_prefix(HEALTH) + "/ready")
    assert ready.status_code == status.HTTP_200_OK

    ping = enforcing_auth_client.get(path_prefix(PING))
    assert ping.status_code == status.HTTP_200_OK
