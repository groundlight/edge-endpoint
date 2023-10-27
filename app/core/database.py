import json
import logging
from typing import Dict, List

import cachetools
from cachetools import TTLCache
from model import ImageQuery
from sqlalchemy import JSON, Boolean, Column, Integer, String, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.asyncio.engine import AsyncEngine
from sqlalchemy.orm import declarative_base, sessionmaker

from .file_paths import DATABASE_FILEPATH

logger = logging.getLogger(__name__)
Base = declarative_base()


class DatabaseManager:
    class DetectorDeployment(Base):
        """
        Schema for the the `detector_deployments` database table
        """

        __tablename__ = "detector_deployments"

        id = Column(Integer, primary_key=True)
        detector_id = Column(String, unique=True)
        api_token = Column(String)
        deployment_created = Column(Boolean)

    class ImageQueriesEdge(Base):
        """
        Schema for the `image_queries_edge` database table.
        """

        __tablename__ = "image_queries_edge"
        id = Column(Integer, primary_key=True)
        image_query_id = Column(String, unique=True)
        image_query = Column(JSON)

    GET_IMAGE_QUERY_RECORD_TTL_CACHE_SIZE = 1000
    GET_IMAGE_QUERY_RECORD_TTL = 300  # 5 minutes
    IMAGE_QUERY_RECORD_CACHE = TTLCache(maxsize=GET_IMAGE_QUERY_RECORD_TTL_CACHE_SIZE, ttl=GET_IMAGE_QUERY_RECORD_TTL)

    def __init__(self, verbose=False) -> None:
        """
        Sets up a database connection and create database tables if they don't exist.
        :param verbose: If True, will print out all executed database queries.
        :type verbose: bool
        :return: None
        :rtype: None
        """
        db_url = f"sqlite+aiosqlite:///{DATABASE_FILEPATH}"
        self._engine: AsyncEngine = create_async_engine(db_url, echo=verbose)

        # Factory for creating new AsyncSession objects.
        self.session = sessionmaker(bind=self._engine, expire_on_commit=False, class_=AsyncSession)

    async def create_detector_deployment_record(self, record: Dict[str, str]) -> None:
        """
        Creates a new record in the `detector_deployments` table.
        :param record: A dictionary containing the detector_id, api_token, and deployment_created fields.
        :type record: Dict[str, str]

        :throws IntegrityError: If the detector_id already exists in the database.
        :return: None
        :rtype: None
        """
        try:
            async with self.session() as session:
                new_record = self.DetectorDeployment(
                    detector_id=record["detector_id"],
                    api_token=record["api_token"],
                    deployment_created=record["deployment_created"],
                )
                session.add(new_record)
                await session.commit()

        except IntegrityError as e:
            await session.rollback()

            # Check if the error specifically occurred due to the unique constraint on the detector_id column.
            # If it did, then we can ignore the error.
            if "detector_id" in str(e.orig):
                logger.debug(f"Detector ID {record['detector_id']} already exists in the database.")
            else:
                logger.error("Integrity error occured", exc_info=True)

    async def update_detector_deployment_record(self, detector_id: str) -> None:
        """
        Check if detector_id is a record in the database. If it is, and the deployment_created field is False,
        update the deployment_created field to True.
        :param detector_id: Detector ID
        :type detector_id: str

        :return: None
        :rtype: None
        """

        try:
            async with self.session() as session:
                query = select(self.DetectorDeployment).filter_by(detector_id=detector_id)
                result = await session.execute(query)

                detector_record = result.scalar_one_or_none()
                if detector_record is None:
                    return

                if not detector_record.deployment_created:
                    detector_record.deployment_created = True
                    await session.commit()
        except IntegrityError:
            logger.debug(f"Error occured while updating database record for {detector_id=}.", exc_info=True)
            await session.rollback()

    async def create_iqe_record(self, record: ImageQuery) -> None:
        """
        Creates a new record in the `image_queries_edge` table.
        :param record: A image query .
        :type record: ImageQuery

        :throws IntegrityError: If the image_query_id already exists in the database.
        :return: None
        :rtype: None
        """
        try:
            async with self.session() as session:
                image_query_id = record.id
                image_query_json = json.loads(record.json())

                new_record = self.ImageQueriesEdge(
                    image_query_id=image_query_id,
                    image_query=image_query_json,
                )
                session.add(new_record)
                await session.commit()

        except IntegrityError as e:
            await session.rollback()

            if "image_query_id" in str(e.orig):
                logger.debug(f"Image query {record.id} already exists in the database table.")
            else:
                logger.error("Integrity error occured", exc_info=True)

    @cachetools.cached(cache=IMAGE_QUERY_RECORD_CACHE)
    async def get_iqe_record(self, image_query_id: str) -> ImageQuery | None:
        """
        Gets a record from the `image_queries_edge` table.
        :param image_query_id: The ID of the image query.
        :type image_query_id: str

        :return: The image query record.
        :rtype: ImageQuery | None
        """
        async with self.session() as session:
            query = select(self.ImageQueriesEdge.image_query).filter_by(image_query_id=image_query_id)
            result = await session.execute(query)
            result_row: dict | None = result.scalar_one_or_none()
            if result_row is None:
                return None

            return ImageQuery(**result_row)

    async def get_detectors_without_deployments(self) -> List[Dict[str, str]] | None:
        async with self.session() as session:
            query = select(self.DetectorDeployment.detector_id, self.DetectorDeployment.api_token).filter_by(
                deployment_created=False
            )
            query_results = await session.execute(query)

            undeployed_detectors = [{"detector_id": row[0], "api_token": row[1]} for row in query_results.fetchall()]
            return undeployed_detectors

        return None

    async def create_tables(self) -> None:
        """
        Checks if the database tables exist and if they don't create them
        :param tables: A list of database tables in the database

        :return: None
        :rtype: None
        """
        try:
            async with self._engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
        except OperationalError:
            logger.error("Could not create database tables.", exc_info=True)

    async def on_shutdown(self) -> None:
        """
        This ensures that we release the resources.
        """
        await self._engine.dispose()
