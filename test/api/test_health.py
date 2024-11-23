from fastapi import status
from fastapi.testclient import TestClient

from app.api.api import HEALTH
from app.api.naming import path_prefix
import pdb


def test_readiness_endpoint(test_client: TestClient):
    url = path_prefix(HEALTH) + "/ready"
    response = test_client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ready"}


def test_liveness_endpoint(test_client: TestClient):
    url = path_prefix(HEALTH) + "/live"
    response = test_client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "alive"}
