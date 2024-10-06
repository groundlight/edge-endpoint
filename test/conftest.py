import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app.db.database import get_db
from app.main import app as edge_app

logger = logging.getLogger(__name__)

SQLALCHEMY_DATABASE_URL = "sqlite://"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


SQLModel.metadata.create_all(bind=engine)


def get_test_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


# Use testing database for all tests
edge_app.dependency_overrides[get_db] = get_test_db


@pytest.fixture(scope="session")
def test_client():
    with TestClient(edge_app) as client:
        yield client
