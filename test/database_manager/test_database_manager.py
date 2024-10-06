import pytest
from model import ImageQuery, ResultTypeEnum
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.core.database import DatabaseManager
from app.core.utils import create_iqe, prefixed_ksuid

NUM_TESTING_RECORDS = 100


@pytest.fixture(scope="module")
def db_manager():
    """Create a database manager for the entire test module."""
    db_manager = DatabaseManager(verbose=False)

    # Create an in-memory database
    # sqlite:///:memory means that the database will be created in memory, so it's ephemeral.
    engine = create_engine("sqlite:///:memory:", echo=False)
    db_manager._engine = engine
    db_manager.session_maker = sessionmaker(bind=db_manager._engine)
    db_manager.create_tables()

    yield db_manager

    db_manager.shutdown()


@pytest.fixture(scope="function")
def database_reset(db_manager: DatabaseManager):
    """Reset the database before every test function."""
    with db_manager.session_maker() as session:
        session.execute(text("DELETE FROM inference_deployments"))
        session.execute(text("DELETE FROM image_queries_edge"))
        session.commit()
        yield


def test_create_inference_deployment_record(db_manager: DatabaseManager, database_reset):
    """Test creating a new detector deployment record."""

    deployments = [
        {
            "detector_id": prefixed_ksuid("det_"),
            "api_token": prefixed_ksuid("api_"),
            "deployment_created": False,
        }
        for _ in range(NUM_TESTING_RECORDS)
    ]

    for deployment in deployments:
        db_manager.create_inference_deployment_record(deployment=deployment)
        with db_manager.session_maker() as session:
            query_text = f"SELECT * FROM inference_deployments WHERE detector_id = '{deployment['detector_id']}'"
            query = session.execute(text(query_text))
            result = query.first()
            assert result.detector_id == deployment["detector_id"]
            assert result.api_token == deployment["api_token"]
            assert result.deployment_created == deployment["deployment_created"] is False


def test_get_detectors_without_deployments(db_manager, database_reset):
    """
    Check that when we retrieve detector deployment records we get what we expect.
    """
    deployments = [
        {
            "detector_id": prefixed_ksuid("det_"),
            "api_token": prefixed_ksuid("api_"),
            "deployment_created": False,
        }
        for _ in range(NUM_TESTING_RECORDS)
    ]

    for deployment in deployments:
        db_manager.create_inference_deployment_record(deployment=deployment)

    undeployed_detectors = db_manager.get_inference_deployments(deployment_created=False)
    assert len(undeployed_detectors) == NUM_TESTING_RECORDS
    for record in undeployed_detectors:
        assert record.detector_id in set([r["detector_id"] for r in deployments])
        assert record.api_token in set([r["api_token"] for r in deployments])


def test_update_inference_deployment_record(db_manager, database_reset):
    """
    Create a few testing records, update the deployment_created field, and check that the update was successful.
    """
    deployments = [
        {
            "detector_id": prefixed_ksuid("det_"),
            "api_token": prefixed_ksuid("api_"),
            "deployment_created": False,
        }
        for _ in range(NUM_TESTING_RECORDS)
    ]

    for deployment in deployments:
        db_manager.create_inference_deployment_record(deployment=deployment)
        db_manager.update_inference_deployment_record(
            detector_id=deployment["detector_id"], fields_to_update={"deployment_created": True}
        )

        with db_manager.session_maker() as session:
            query_text = f"SELECT * FROM inference_deployments WHERE detector_id = '{deployment['detector_id']}'"
            query = session.execute(text(query_text))
            result = query.first()
            assert result.detector_id == deployment["detector_id"]
            assert result.api_token == deployment["api_token"]
            assert bool(result.deployment_created) is True


def test_update_api_token_for_detector(db_manager, database_reset):
    deployment = {
        "detector_id": prefixed_ksuid("det_"),
        "api_token": prefixed_ksuid("api_"),
        "deployment_created": False,
    }
    db_manager.create_inference_deployment_record(deployment=deployment)
    detectors = db_manager.get_inference_deployments(detector_id=deployment["detector_id"])
    assert len(detectors) == 1
    assert detectors[0].api_token == deployment["api_token"]
    assert bool(detectors[0].deployment_created) is False

    # Now change the API token
    new_api_token = prefixed_ksuid("api_")
    db_manager.update_inference_deployment_record(
        detector_id=deployment["detector_id"], fields_to_update={"api_token": new_api_token}
    )

    # Check that the API token has been updated
    detectors = db_manager.get_inference_deployments(detector_id=deployment["detector_id"])
    assert len(detectors) == 1
    assert detectors[0].api_token == new_api_token
    assert bool(detectors[0].deployment_created) is False


def test_get_inference_deployments_raises_sqlalchemy_error(db_manager: DatabaseManager, database_reset):
    deployment = {
        "detector_id": prefixed_ksuid("det_"),
        "api_token": prefixed_ksuid("api_"),
        "deployment_created": False,
    }
    db_manager.create_inference_deployment_record(deployment=deployment)

    # We will query with invalid parameters and make sure that we get an error
    with pytest.raises(SQLAlchemyError):
        db_manager.get_inference_deployments(detector_id=deployment["detector_id"], image_query_id="invalid_id")


def test_get_iqe_record(db_manager, database_reset):
    image_query: ImageQuery = create_iqe(
        detector_id=prefixed_ksuid("det_"),
        result_type=ResultTypeEnum.binary_classification,
        label="test_label",
        confidence=0.5,
        query="test_query",
        confidence_threshold=0.9,
    )
    db_manager.create_iqe_record(iq=image_query)

    # Get the record
    retrieved_record = db_manager.get_iqe_record(image_query_id=image_query.id)
    assert retrieved_record == image_query
