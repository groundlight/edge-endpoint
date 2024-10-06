import pytest
from model import ImageQuery, ResultTypeEnum
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import SQLModel

from app.core.utils import create_iqe, prefixed_ksuid
from app.db.models import InferenceDeployment

NUM_TESTING_RECORDS = 100


@pytest.fixture(scope="module")
def db_manager():
    """Create a database manager for the entire test module."""
    # Create an in-memory database
    # sqlite:///:memory means that the database will be created in memory, so it's ephemeral.
    engine = create_engine("sqlite:///:memory:", echo=False)
    db_manager = DatabaseManager(engine=engine, verbose=False)
    db_manager.create_tables()

    yield db_manager

    # Tear down
    engine.dispose()


@pytest.fixture(scope="function")
def reset_db(db_manager: DatabaseManager):
    """Drop all tables and recreate them before each test function."""
    SQLModel.metadata.drop_all(bind=db_manager._engine)
    db_manager.create_tables()
    yield


def test_create_inference_deployment_record(db_manager: DatabaseManager, reset_db):
    """Test creating a new detector deployment record."""
    test_deployments = [
        InferenceDeployment(
            detector_id=prefixed_ksuid("det_"), api_token=prefixed_ksuid("api_"), deployment_created=False
        )
        for _ in range(NUM_TESTING_RECORDS)
    ]
    for deployment in test_deployments:
        db_manager.create_inference_deployment_record(deployment=deployment)
        with db_manager.session_maker() as session:
            result = session.query(InferenceDeployment).filter_by(detector_id=deployment.detector_id).first()
            assert deployment == result


def test_get_detectors_without_deployments(db_manager, reset_db):
    """Check that when we retrieve detector deployment records we get what we expect."""
    test_deployments = [
        InferenceDeployment(
            detector_id=prefixed_ksuid("det_"), api_token=prefixed_ksuid("api_"), deployment_created=False
        )
        for _ in range(NUM_TESTING_RECORDS)
    ]

    for deployment in test_deployments:
        db_manager.create_inference_deployment_record(deployment=deployment)

    undeployed_detectors = db_manager.get_inference_deployments(deployment_created=False)
    assert len(undeployed_detectors) == NUM_TESTING_RECORDS
    for undeployed_detector in undeployed_detectors:
        assert undeployed_detector.detector_id in set([r.detector_id for r in test_deployments])
        assert undeployed_detector.api_token in set([r.api_token for r in test_deployments])


def test_update_inference_deployment_record(db_manager, reset_db):
    """Check that we can update an existing detector deployment record."""
    test_deployments = [
        InferenceDeployment(
            detector_id=prefixed_ksuid("det_"), api_token=prefixed_ksuid("api_"), deployment_created=False
        )
        for _ in range(NUM_TESTING_RECORDS)
    ]
    for deployment in test_deployments:
        db_manager.create_inference_deployment_record(deployment=deployment)
        db_manager.update_inference_deployment_record(
            detector_id=deployment.detector_id, fields_to_update={"deployment_created": True}
        )

        with db_manager.session_maker() as session:
            result = session.query(InferenceDeployment).filter_by(detector_id=deployment.detector_id).first()
            assert result.detector_id == deployment.detector_id
            assert result.api_token == deployment.api_token
            assert bool(result.deployment_created) is True
            assert result.deployment_name is not None


def test_update_api_token_for_inference_deployment(db_manager, reset_db):
    deployment = InferenceDeployment(
        detector_id=prefixed_ksuid("det_"), api_token=prefixed_ksuid("api_"), deployment_created=False
    )
    db_manager.create_inference_deployment_record(deployment=deployment)
    detectors = db_manager.get_inference_deployments(detector_id=deployment.detector_id)
    assert len(detectors) == 1
    assert detectors[0] == deployment

    # Now change the API token
    new_api_token = prefixed_ksuid("api_")
    db_manager.update_inference_deployment_record(
        detector_id=deployment.detector_id, fields_to_update={"api_token": new_api_token}
    )

    # Check that the API token has been updated
    detectors = db_manager.get_inference_deployments(detector_id=deployment.detector_id)
    assert len(detectors) == 1
    assert detectors[0].api_token == new_api_token


def test_get_inference_deployments_raises_sqlalchemy_error(db_manager: DatabaseManager, reset_db):
    deployment = InferenceDeployment(
        detector_id=prefixed_ksuid("det_"), api_token=prefixed_ksuid("api_"), deployment_created=False
    )
    db_manager.create_inference_deployment_record(deployment=deployment)

    # We will query with invalid parameters and make sure that we get an error
    # Here `image_query_id` is not a valid field in the `inference_deployments` table, so
    # we should get an error.
    with pytest.raises(SQLAlchemyError):
        db_manager.get_inference_deployments(detector_id=deployment.detector_id, image_query_id="invalid_id")


def test_get_iqe_record(db_manager, reset_db):
    """Check that we can retrieve an image query record exactly as it was created."""
    image_query: ImageQuery = create_iqe(
        detector_id=prefixed_ksuid("det_"),
        result_type=ResultTypeEnum.binary_classification,
        label="test_label",
        confidence=0.5,
        query="test_query",
        confidence_threshold=0.9,
        text="test_text",
    )

    db_manager.create_iqe_record(iq=image_query)

    retrieved_record = db_manager.get_iqe_record(image_query_id=image_query.id)
    assert retrieved_record == image_query
