from test.parsing import parse

import pytest
from fastapi.testclient import TestClient

from app.api.api import EDGE_INFO
from app.api.naming import path_prefix
from app.schemas.edge_info import EdgeInfo


@pytest.mark.parametrize(
    "configured_endpoint, expected_upstream",
    [
        ("https://api.groundlight.ai/", "https://api.groundlight.ai"),
        ("https://api.groundlight.dev.axon.com", "https://api.groundlight.dev.axon.com"),
        ("https://api.groundlight.usa.axon.com/device-api/", "https://api.groundlight.usa.axon.com"),
        ("http://localhost:8000", "http://localhost:8000"),
    ],
)
def test_edge_info_reports_upstream_origin(
    test_client: TestClient, monkeypatch: pytest.MonkeyPatch, configured_endpoint: str, expected_upstream: str
):
    monkeypatch.setenv("GROUNDLIGHT_ENDPOINT", configured_endpoint)
    edge_info = parse(test_client.get(path_prefix(EDGE_INFO)), EdgeInfo)
    assert edge_info.upstream_endpoint == expected_upstream


def test_edge_info_defaults_to_groundlight_cloud(test_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GROUNDLIGHT_ENDPOINT", raising=False)
    edge_info = parse(test_client.get(path_prefix(EDGE_INFO)), EdgeInfo)
    assert edge_info.upstream_endpoint == "https://api.groundlight.ai"
