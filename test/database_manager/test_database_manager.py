import asyncio
from copy import deepcopy

import pytest
import pytest_asyncio
from model import ImageQuery
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.database import DatabaseManager
from app.core.utils import create_iqe, prefixed_ksuid

NUM_TESTING_RECORDS = 100


@pytest.fixture(scope="module")
def db_manager():
    """
    Create a database manager for the entire test module.
    """
    db_manager = DatabaseManager(verbose=False)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    db_manager._engine = engine
    db_manager.session = sessionmaker(bind=db_manager._engine, expire_on_commit=False, class_=AsyncSession)
    asyncio.run(db_manager.create_tables())

    yield db_manager

    # Tear down
    asyncio.run(db_manager.on_shutdown())


@pytest_asyncio.fixture(scope="function")
async def database_reset(db_manager: DatabaseManager):
    """
    Reset the database before every test function and yield control to the test function.
    """
    async with db_manager.session() as session:
        await session.execute(text("DELETE FROM detector_deployments"))
        await session.execute(text("DELETE FROM image_queries_edge"))
        await session.commit()
        yield


# @pytest.mark.asyncio
# async def test_create_tables_raises_operational_error(db_manager: DatabaseManager, database_reset):

#     # Deep copy the database manager so that we can monkey patch the `DetectorDeployment` table
#     # and then restore it later.
#     new_db_manager = deepcopy(db_manager)

#     Base = declarative_base()
#     async with new_db_manager.session() as session:

#         # We should get an error here because the schema is not well-defined.
#         # SQLAlchemy will try to look for any fields in the `detector_deployment`
#         # table, and when it doesn't find any, it will raise an error.
#         detector_deployment_table = new_db_manager.DetectorDeployment
#         with pytest.raises(SQLAlchemyError):

#             class MonkeyPatchDetectorDeploymentTable(Base):
#                 __tablename__ = "detector_deployments"

#             new_db_manager.DetectorDeployment = MonkeyPatchDetectorDeploymentTable
#             await new_db_manager.create_tables()

#         await session.rollback()

#     del new_db_manager


@pytest.mark.asyncio
async def test_create_detector_deployment_record(db_manager: DatabaseManager, database_reset):
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
        await db_manager.create_detector_deployment_record(record=record)
        async with db_manager.session() as session:
            query_text = f"SELECT * FROM detector_deployments WHERE detector_id = '{record['detector_id']}'"
            query = await session.execute(text(query_text))
            result = query.first()
            assert result.detector_id == record["detector_id"]
            assert result.api_token == record["api_token"]
            assert result.deployment_created == record["deployment_created"] is False


@pytest.mark.asyncio
async def test_get_detectors_without_deployments(db_manager: DatabaseManager, database_reset):
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
        await db_manager.create_detector_deployment_record(record=record)

    undeployed_detectors = await db_manager.query_detector_deployments(deployment_created=False)
    assert len(undeployed_detectors) == NUM_TESTING_RECORDS
    for record in undeployed_detectors:
        assert record["detector_id"] in [r["detector_id"] for r in records]
        assert record["api_token"] in [r["api_token"] for r in records]


@pytest.mark.asyncio
async def test_get_iqe_record(db_manager: DatabaseManager, database_reset):
    image_query: ImageQuery = create_iqe(
        detector_id=prefixed_ksuid("det_"), label="test_label", confidence=0.5, query="test_query"
    )
    await db_manager.create_iqe_record(record=image_query)

    # Get the record
    retrieved_record = await db_manager.get_iqe_record(image_query_id=image_query.id)
    assert retrieved_record == image_query


# @pytest.mark.asyncio
# async def test_create_iqe_record_raises_integrity_error(db_manager: DatabaseManager, database_reset):
#     """
#     Tests that if we try to create an image query record that already exists, we get an IntegrityError.
#     """
#     image_query: ImageQuery = create_iqe(
#         detector_id=prefixed_ksuid("det_"), label="test_label", confidence=0.5, query="test_query"
#     )
#     await db_manager.create_iqe_record(record=image_query)

#     with pytest.raises(IntegrityError):
#         await db_manager.create_iqe_record(record=image_query)

#     # Try to delete the record and then create it again to make sure that no error
#     # gets raised.
#     async with db_manager.session() as session:
#         await session.execute(text(f"DELETE FROM image_queries_edge WHERE id = '{image_query.id}'"))
#         session.commit()

#     # Now create the record again
#     await db_manager.create_iqe_record(record=image_query)
#     retrieved_record = await db_manager.get_iqe_record(image_query_id=image_query.id)
#     assert retrieved_record == image_query


@pytest.mark.asyncio
async def test_update_detector_deployment_record(db_manager: DatabaseManager, database_reset):
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
        await db_manager.create_detector_deployment_record(record=record)
        await db_manager.update_detector_deployment_record(
            detector_id=record["detector_id"], new_record={"deployment_created": True}
        )

        async with db_manager.session() as session:
            query_text = f"SELECT * FROM detector_deployments WHERE detector_id = '{record['detector_id']}'"
            query = await session.execute(text(query_text))
            result = query.first()
            assert result.detector_id == record["detector_id"]
            assert result.api_token == record["api_token"]
            assert bool(result.deployment_created) is True


@pytest.mark.asyncio
async def test_update_api_token_for_detector(db_manager: DatabaseManager, database_reset):
    record = {
        "detector_id": prefixed_ksuid("det_"),
        "api_token": prefixed_ksuid("api_"),
        "deployment_created": False,
    }
    await db_manager.create_detector_deployment_record(record=record)
    detectors = await db_manager.query_detector_deployments(detector_id=record["detector_id"])
    assert len(detectors) == 1
    assert detectors[0]["api_token"] == record["api_token"]
    assert bool(detectors[0]["deployment_created"]) is False

    # Now change the API token
    new_api_token = prefixed_ksuid("api_")
    await db_manager.update_detector_deployment_record(
        detector_id=record["detector_id"], new_record={"api_token": new_api_token}
    )

    # Check that the API token has been updated
    detectors = await db_manager.query_detector_deployments(detector_id=record["detector_id"])
    assert len(detectors) == 1
    assert detectors[0]["api_token"] == new_api_token
    assert bool(detectors[0]["deployment_created"]) is False


@pytest.mark.asyncio
async def test_create_detector_record_raises_integrity_error(db_manager: DatabaseManager, database_reset):
    records = [
        {
            "detector_id": prefixed_ksuid("det_"),
            "api_token": prefixed_ksuid("api_"),
            "deployment_created": False,
        }
        for _ in range(NUM_TESTING_RECORDS)
    ]

    for record in records:
        await db_manager.create_detector_deployment_record(record=record)

        with pytest.raises(IntegrityError):
            await db_manager.create_detector_deployment_record(record=record)


@pytest.mark.asyncio
async def test_query_detector_deployments_raises_sqlalchemy_error(db_manager: DatabaseManager, database_reset):
    detector_record = {
        "detector_id": prefixed_ksuid("det_"),
        "api_token": prefixed_ksuid("api_"),
        "deployment_created": False,
    }
    await db_manager.create_detector_deployment_record(record=detector_record)

    # We will query with invalid parameters and make sure that we get an error
    # Here `image_query_id` is not a valid field in the `detector_deployments` table, so
    # we should get an error.
    with pytest.raises(SQLAlchemyError):
        await db_manager.query_detector_deployments(
            detector_id=detector_record["detector_id"], image_query_id="invalid_id"
        )
