import asyncio

import pytest
import pytest_asyncio
from model import ImageQuery
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import DatabaseManager
from app.core.utils import create_iqe, prefixed_ksuid

NUM_TESTING_RECORDS = 100


@pytest.fixture(scope="module")
def db_manager():
    """
    Create a database manager for the entire test module.
    """
    db_manager = DatabaseManager(verbose=False)
    engine = create_engine("sqlite:///:memory:", echo=False)
    db_manager._engine = engine
    db_manager.session_maker = sessionmaker(bind=db_manager._engine)
    db_manager.create_tables()

    yield db_manager

    # Tear down
    db_manager.shutdown()


@pytest.fixture(scope="function")
def database_reset(db_manager: DatabaseManager):
    """
    Reset the database before every test function and yield control to the test function.
    """
    with db_manager.session_maker() as session:
        session.execute(text("DELETE FROM inference_deployments"))
        session.execute(text("DELETE FROM image_queries_edge"))
        session.commit()
        yield


def test_create_inference_deployment_record(db_manager: DatabaseManager, database_reset):
    """
    Test creating a new detector deployment record.
    """

    records = [
        {
            "detector_id": prefixed_ksuid("det_"),
            "api_token": prefixed_ksuid("api_"),
            "deployment_created": False,
        }
        for _ in range(NUM_TESTING_RECORDS)
    ]

    for record in records:
        db_manager.create_inference_deployment_record(record=record)
        with db_manager.session_maker() as session:
            query_text = f"SELECT * FROM inference_deployments WHERE detector_id = '{record['detector_id']}'"
            query = session.execute(text(query_text))
            result = query.first()
            assert result.detector_id == record["detector_id"]
            assert result.api_token == record["api_token"]
            assert result.deployment_created == record["deployment_created"] == False


def test_get_detectors_without_deployments(db_manager, database_reset):
    """
    Check that when we retrieve detector deployment records we get what we expect.
    """
    records = [
        {
            "detector_id": prefixed_ksuid("det_"),
            "api_token": prefixed_ksuid("api_"),
            "deployment_created": False,
        }
        for _ in range(NUM_TESTING_RECORDS)
    ]

    for record in records:
        db_manager.create_inference_deployment_record(record=record)

    undeployed_detectors = db_manager.query_inference_deployments(deployment_created=False)
    assert len(undeployed_detectors) == NUM_TESTING_RECORDS
    for record in undeployed_detectors:
        assert record["detector_id"] in [r["detector_id"] for r in records]
        assert record["api_token"] in [r["api_token"] for r in records]


def test_get_iqe_record(db_manager, database_reset):
    image_query: ImageQuery = create_iqe(
        detector_id=prefixed_ksuid("det_"), label="test_label", confidence=0.5, query="test_query"
    )
    db_manager.create_iqe_record(record=image_query)

    # Get the record
    retrieved_record = db_manager.get_iqe_record(image_query_id=image_query.id)
    assert retrieved_record == image_query


def test_update_inference_deployment_record(db_manager, database_reset):
    """
    Create a few testing records, update the deployment_created field, and check that the update was successful.
    """
    records = [
        {
            "detector_id": prefixed_ksuid("det_"),
            "api_token": prefixed_ksuid("api_"),
            "deployment_created": False,
        }
        for _ in range(NUM_TESTING_RECORDS)
    ]

    for record in records:
        db_manager.create_inference_deployment_record(record=record)
        db_manager.update_inference_deployment_record(
            detector_id=record["detector_id"], new_record={"deployment_created": True}
        )

        with db_manager.session_maker() as session:
            query_text = f"SELECT * FROM inference_deployments WHERE detector_id = '{record['detector_id']}'"
            query = session.execute(text(query_text))
            result = query.first()
            assert result.detector_id == record["detector_id"]
            assert result.api_token == record["api_token"]
            assert bool(result.deployment_created) is True


def test_update_api_token_for_detector(db_manager, database_reset):
    record = {
        "detector_id": prefixed_ksuid("det_"),
        "api_token": prefixed_ksuid("api_"),
        "deployment_created": False,
    }
    db_manager.create_inference_deployment_record(record=record)
    detectors = db_manager.query_inference_deployments(detector_id=record["detector_id"])
    assert len(detectors) == 1
    assert detectors[0]["api_token"] == record["api_token"]
    assert bool(detectors[0]["deployment_created"]) == False

    # Now change the API token
    new_api_token = prefixed_ksuid("api_")
    db_manager.update_inference_deployment_record(
        detector_id=record["detector_id"], new_record={"api_token": new_api_token}
    )

    # Check that the API token has been updated
    detectors = db_manager.query_inference_deployments(detector_id=record["detector_id"])
    assert len(detectors) == 1
    assert detectors[0]["api_token"] == new_api_token
    assert bool(detectors[0]["deployment_created"]) == False


def test_create_detector_record_raises_validation_error(db_manager: DatabaseManager, database_reset):
    """
    Creating detector record with invalid detector_id should raise a ValueError.
    """
    records = [
        {
            "detector_id": prefixed_ksuid("det_") + prefixed_ksuid("_"),
            "api_token": prefixed_ksuid("api_"),
            "deployment_created": False,
        }
        for _ in range(NUM_TESTING_RECORDS)
    ]

    for record in records:
        with pytest.raises(ValueError):
            db_manager.create_inference_deployment_record(record=record)


def test_query_inference_deployments_raises_sqlalchemy_error(db_manager: DatabaseManager, database_reset):
    detector_record = {
        "detector_id": prefixed_ksuid("det_"),
        "api_token": prefixed_ksuid("api_"),
        "deployment_created": False,
    }
    db_manager.create_inference_deployment_record(record=detector_record)

    # We will query with invalid parameters and make sure that we get an error
    # Here `image_query_id` is not a valid field in the `inference_deployments` table, so
    # we should get an error.
    with pytest.raises(SQLAlchemyError):
        db_manager.query_inference_deployments(detector_id=detector_record["detector_id"], image_query_id="invalid_id")
