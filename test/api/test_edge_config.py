from fastapi.testclient import TestClient


def test_set_edge_config_invalid_body(test_client: TestClient):
    """PUT /edge-config with an invalid body should return 422."""
    response = test_client.put("/edge-config", json={"detectors": "not_a_list"})
    assert response.status_code == 422


def test_set_edge_config_valid_body(test_client: TestClient):
    """PUT /edge-config with a valid body should return 200."""
    response = test_client.put("/edge-config", json={})
    assert response.status_code == 200
