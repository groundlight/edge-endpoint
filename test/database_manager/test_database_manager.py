import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.core.database import DatabaseManager
from app.core.models import Base
from app.core.utils import prefixed_ksuid

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
    db_manager.reset_database()


def test_create_or_update_inference_deployment_record(db_manager: DatabaseManager, database_reset):
    """Test creating a new detector deployment record."""
    deployments = []

    for _ in range(NUM_TESTING_RECORDS):
        detector_id = prefixed_ksuid("det_")
        edge_model_name = detector_id + "/primary"
        oodd_model_name = detector_id + "/oodd"
        api_token = prefixed_ksuid("api_")
        deployment_created = False
        deployments.append({
            "model_name": edge_model_name,
            "detector_id": detector_id,
            "api_token": api_token,
            "deployment_created": deployment_created,
        })
        deployments.append({
            "model_name": oodd_model_name,
            "detector_id": detector_id,
            "api_token": api_token,
            "deployment_created": deployment_created,
        })

    for deployment in deployments:
        db_manager.create_or_update_inference_deployment_record(deployment=deployment)
        with db_manager.session_maker() as session:
            query_text = f"SELECT * FROM inference_deployments WHERE model_name = '{deployment['model_name']}'"
            query = session.execute(text(query_text))
            result = query.first()
            assert result.model_name == deployment["model_name"]
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
            "model_name": prefixed_ksuid("det_") + "/oodd",
            "api_token": prefixed_ksuid("api_"),
            "deployment_created": False,
        }
        for _ in range(NUM_TESTING_RECORDS)
    ]

    for deployment in deployments:
        db_manager.create_or_update_inference_deployment_record(deployment=deployment)

    undeployed_detectors = db_manager.get_inference_deployment_records(deployment_created=False)
    assert len(undeployed_detectors) == NUM_TESTING_RECORDS
    for record in undeployed_detectors:
        assert record.detector_id in set([r["detector_id"] for r in deployments])
        assert record.api_token in set([r["api_token"] for r in deployments])
        assert record.model_name in set([r["model_name"] for r in deployments])


def test_update_inference_deployment_record(db_manager, database_reset):
    """
    Create a few testing records, update the deployment_created field, and check that the update was successful.
    """
    deployments = []

    for _ in range(NUM_TESTING_RECORDS):
        detector_id = prefixed_ksuid("det_")
        edge_model_name = detector_id + "/primary"
        oodd_model_name = detector_id + "/oodd"
        api_token = prefixed_ksuid("api_")
        deployment_created = False
        deployments.append({
            "model_name": edge_model_name,
            "detector_id": detector_id,
            "api_token": api_token,
            "deployment_created": deployment_created,
        })
        deployments.append({
            "model_name": oodd_model_name,
            "detector_id": detector_id,
            "api_token": api_token,
            "deployment_created": deployment_created,
        })

    for deployment in deployments:
        db_manager.create_or_update_inference_deployment_record(deployment=deployment)
        db_manager.update_inference_deployment_record(
            model_name=deployment["model_name"], fields_to_update={"deployment_created": True}
        )

        with db_manager.session_maker() as session:
            query_text = f"SELECT * FROM inference_deployments WHERE model_name = '{deployment['model_name']}'"
            query = session.execute(text(query_text))
            result = query.first()
            assert result.model_name == deployment["model_name"]
            assert result.detector_id == deployment["detector_id"]
            assert result.api_token == deployment["api_token"]
            assert bool(result.deployment_created) is True


def test_update_api_token_for_detector(db_manager, database_reset):
    deployment = {
        "detector_id": prefixed_ksuid("det_"),
        "model_name": prefixed_ksuid("det_") + "/primary",
        "api_token": prefixed_ksuid("api_"),
        "deployment_created": False,
    }
    db_manager.create_or_update_inference_deployment_record(deployment=deployment)
    detectors = db_manager.get_inference_deployment_records(model_name=deployment["model_name"])
    assert len(detectors) == 1
    assert detectors[0].api_token == deployment["api_token"]
    assert bool(detectors[0].deployment_created) is False

    # Now change the API token
    new_api_token = prefixed_ksuid("api_")
    db_manager.update_inference_deployment_record(
        model_name=deployment["model_name"], fields_to_update={"api_token": new_api_token}
    )

    # Check that the API token has been updated
    detectors = db_manager.get_inference_deployment_records(model_name=deployment["model_name"])
    assert len(detectors) == 1
    assert detectors[0].api_token == new_api_token
    assert bool(detectors[0].deployment_created) is False


def test_create_drop_reset_database_tables(db_manager, database_reset):
    # Ensure tables are created first
    db_manager.create_tables()
    inspector = inspect(db_manager._engine)
    tables = inspector.get_table_names()
    assert set(tables) == set(Base.metadata.tables.keys())

    db_manager.drop_tables()
    inspector = inspect(db_manager._engine)
    tables = inspector.get_table_names()
    assert len(tables) == 0

    db_manager.reset_database()
    inspector = inspect(db_manager._engine)
    tables = inspector.get_table_names()
    assert set(tables) == set(Base.metadata.tables.keys())
