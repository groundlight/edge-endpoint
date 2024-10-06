from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.main import app as edge_app


@pytest.fixture(scope="session")
def engine():
    # Create an in-memory SQLite database for testing
    test_db_url = "sqlite:///:memory:"
    return create_engine(test_db_url)


@pytest.fixture
def test_client(engine):
    # Inject the test database engine into the test app
    with patch("app.db.manager.get_database_engine", return_value=engine):
        with TestClient(edge_app) as client:
            yield client
