from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.escalation_queue.queue_writer import QueueWriter
from app.main import app
from app.metrics.iq_activity import FilesystemActivityTrackingHelper


@pytest.fixture(scope="module")
def test_client(tmp_path_factory) -> TestClient:
    """App TestClient with in-memory DB and auth bypassed for unit tests."""

    def mock_get_database_url():
        """Use an in-memory sqlite database for testing."""
        return "sqlite:///:memory:"

    mock_auth = MagicMock()
    mock_auth.validate_request = MagicMock()  # accept every request in unit tests
    queue_dir = tmp_path_factory.mktemp("escalation_queue")
    metrics_dir = tmp_path_factory.mktemp("edge-metrics")
    active_config_path = tmp_path_factory.mktemp("edge_config") / "active-edge-config.yaml"
    metrics_tracker = FilesystemActivityTrackingHelper(base_dir=str(metrics_dir))

    with (
        patch("app.core.database.get_database_url", mock_get_database_url),
        patch("app.main.edge_endpoint_auth_manager", return_value=mock_auth),
        patch("app.core.edge_endpoint_auth.edge_endpoint_auth_manager", return_value=mock_auth),
        # Avoid requiring /opt/groundlight on developer machines.
        patch("app.core.app_state.QueueWriter", lambda: QueueWriter(base_dir=str(queue_dir))),
        patch("app.core.edge_config_manager.ACTIVE_EDGE_CONFIG_PATH", str(active_config_path)),
        patch("app.main.ACTIVE_EDGE_CONFIG_PATH", str(active_config_path)),
        patch("app.metrics.iq_activity._tracker", return_value=metrics_tracker),
    ):
        with TestClient(app) as client:
            # Context manager handles lifecycle of the TestClient
            yield client
