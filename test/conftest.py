from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

TEST_URL = "http://testserver"


@pytest.fixture(scope="module")
def test_client() -> TestClient:
    def mock_get_database_url():
        """Use an in-memory sqlite database for testing."""
        return "sqlite:///:memory:"

    with patch("app.core.database.get_database_url", mock_get_database_url):
        with TestClient(app, base_url="http://testserver") as client:
            # Context manager handles lifecycle of the TestClient
            yield client
