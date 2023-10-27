import asyncio
from typing import Dict, List

import pytest
import pytest_asyncio
from model import ImageQuery
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
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
    Reset the database before every test function
    """
    async with db_manager.session() as session:
        await session.execute(text("DELETE FROM detector_deployments"))
        await session.execute(text("DELETE FROM image_queries_edge"))
        await session.commit()
        yield


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

    undeployed_detectors = await db_manager.get_detectors_without_deployments()
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
        await db_manager.update_detector_deployment_record(detector_id=record["detector_id"])

        async with db_manager.session() as session:
            query_text = f"SELECT * FROM detector_deployments WHERE detector_id = '{record['detector_id']}'"
            query = await session.execute(text(query_text))
            result = query.first()
            assert result.detector_id == record["detector_id"]
            assert result.api_token == record["api_token"]
            assert result.deployment_created == True
