import time
from unittest import mock

import pytest
import requests
from fastapi.testclient import TestClient
from groundlight.edge import DEFAULT, EdgeEndpointConfig

from app.core import edge_inference
from app.core.naming import get_edge_inference_service_name

PROBE_LATENCY_SEC = 0.1


def det_id(i: int) -> str:
    return f"det_{i:027d}"


def put_detectors(test_client: TestClient, detector_ids: list[str]) -> None:
    config = EdgeEndpointConfig()
    for did in detector_ids:
        config.add_detector(did, DEFAULT)
    response = test_client.put("/edge-config", json=config.to_payload())
    assert response.status_code == 200, response.text


@pytest.fixture(autouse=True)
def clean_state(test_client: TestClient):
    edge_inference.ttl_cache.clear()
    yield
    edge_inference.ttl_cache.clear()
    test_client.put("/edge-config", json={})


def test_reports_readiness_per_detector(test_client: TestClient):
    ready_id, unreachable_id = det_id(1), det_id(2)
    put_detectors(test_client, [ready_id, unreachable_id])
    unreachable_host = get_edge_inference_service_name(unreachable_id)

    def fake_get(url: str, timeout: float):
        if unreachable_host in url:
            raise requests.exceptions.ConnectionError("connection refused")
        return mock.Mock(status_code=200)

    with mock.patch.object(edge_inference.requests, "get", side_effect=fake_get):
        response = test_client.get("/edge-detector-readiness")

    assert response.status_code == 200
    assert response.json() == {ready_id: {"ready": True}, unreachable_id: {"ready": False}}


def test_latency_does_not_scale_with_detector_count(test_client: TestClient):
    """Probes must run concurrently: the SDK's set_config polls this endpoint with a 10s read timeout."""
    detector_ids = [det_id(i) for i in range(30)]
    put_detectors(test_client, detector_ids)

    def slow_get(url: str, timeout: float):
        time.sleep(PROBE_LATENCY_SEC)
        return mock.Mock(status_code=200)

    with mock.patch.object(edge_inference.requests, "get", side_effect=slow_get):
        start = time.perf_counter()
        response = test_client.get("/edge-detector-readiness")
        elapsed = time.perf_counter() - start

    assert response.status_code == 200
    assert all(entry["ready"] for entry in response.json().values())
    # Serial probing of 30 detectors x (primary + OODD) would take 30 * 2 * 0.1s = 6s.
    assert elapsed < 10 * PROBE_LATENCY_SEC
