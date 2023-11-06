import datetime
import json
import logging
from logging.handlers import RotatingFileHandler
import re
from typing import Dict, List, Tuple

import cachetools
from cachetools import TTLCache
from model import ImageQuery
from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.asyncio.engine import AsyncEngine
from sqlalchemy.orm import declarative_base, sessionmaker, validates

from .file_paths import DATABASE_FILEPATH, DATABASE_ORM_LOG_FILE

logger = logging.getLogger(__name__)
Base = declarative_base()


def validate_uid(uid: str) -> None:
    """
    Validates that the passed in UID is either a valid UUID4 or KSUID with or
    without a prefix.
    """
    try:
        uuid.UUID(uid)
        return
    except:
        pass

    alphanumeric = re.compile("^[a-z0-9]+$", re.IGNORECASE)
    if "_" in uid:
        prefix, suffix = uid.split("_", 1)
        if len(prefix) > 10:
            raise ValueError(f"Invalid ID {uid} - prefix too long")
        if not alphanumeric.match(prefix):
            raise ValueError(f"Invalid ID {uid} - prefix has non-alphanumeric")
        uid = suffix
    if len(uid) < 27:
        raise ValueError(f"Invalid ID {uid} - id is too short")
    if not alphanumeric.match(uid):
        raise ValueError(f"Invalid ID {uid} - id has non-alphanumeric")


class DatabaseManager:
    class DetectorDeployment(Base):
        """
        Schema for the the `detector_deployments` database table
        """

        __tablename__ = "detector_deployments"
        id = Column(Integer, primary_key=True, nullable=True, autoincrement=True)
        detector_id = Column(String(44), unique=True, nullable=False, comment="Detector ID")
        api_token = Column(String(44), nullable=False, comment="API token")
        deployment_created = Column(
            Boolean,
            default=False,
            nullable=False,
            comment="Indicates if the given detector already has an inference deployment.",
        )
        created_at = Column(
            DateTime, nullable=True, default=datetime.datetime.utcnow, comment="Timestamp of record creation"
        )
        updated_at = Column(
            DateTime,
            nullable=True,
            default=datetime.datetime.utcnow,
            onupdate=datetime.datetime.utcnow,
            comment="Timestamp of record update",
        )

        @validates("detector_id")
        def validate_uid(self, key, value):
            validate_uid(value)
            return value

    class ImageQueriesEdge(Base):
        """
        Schema for the `image_queries_edge` database table.
        """

        __tablename__ = "image_queries_edge"
        image_query_id = Column(
            String,
            primary_key=True,
            unique=True,
            nullable=False,
            index=True,
            comment="Image query ID. This is expected to be prefixed with `iqe_`.",
        )
        image_query = Column(JSON, nullable=False, comment="JSON representation of the ImageQuery data model.")

        @validates("image_query_id")
        def validate_uid(self, key, value):
            validate_uid(value)
            return value

    GET_IMAGE_QUERY_RECORD_TTL_CACHE_SIZE = 1000
    GET_IMAGE_QUERY_RECORD_TTL = 300  # 5 minutes
    IMAGE_QUERY_RECORD_CACHE = TTLCache(maxsize=GET_IMAGE_QUERY_RECORD_TTL_CACHE_SIZE, ttl=GET_IMAGE_QUERY_RECORD_TTL)

    def __init__(self, verbose=False) -> None:
        """
        Initializes the database engine which manages creating and closing connection pools efficiently.
        :param verbose: If True, will print out all executed database queries.
        """

        log_level = logger.getEffectiveLevel()
        if verbose or log_level == logging.DEBUG:
            file_handler = RotatingFileHandler(DATABASE_ORM_LOG_FILE, maxBytes=10_000_000, backupCount=10)
            formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            file_handler.setFormatter(formatter)

            sqlalchemy_logger = logging.getLogger("sqlalchemy.engine")
            sqlalchemy_logger.setLevel(logging.INFO)
            sqlalchemy_logger.addHandler(file_handler)

        db_url = f"sqlite+aiosqlite:///{DATABASE_FILEPATH}"
        self._engine: AsyncEngine = create_async_engine(db_url, echo=verbose)

        # Factory for creating new AsyncSession objects.
        # AsyncSession is a mutable, stateful object which represents a single database
        # transaction in progress.
        self.session = sessionmaker(bind=self._engine, expire_on_commit=True, class_=AsyncSession)

    async def create_detector_deployment_record(self, record: Dict[str, str]) -> None:
        """
        Creates a new record in the `detector_deployments` table. If the record exists, but the API token has
        changed, we will update the record with the new API token.
        :param record: A dictionary containing the detector_id, api_token, and deployment_created fields.
        :type record: Dict[str, str]

        :throws IntegrityError: If the detector_id already exists in the database.
        :return: None
        :rtype: None
        """
        api_token = record["api_token"]
        try:
            async with self.session() as session:
                new_record = self.DetectorDeployment(
                    detector_id=record["detector_id"],
                    api_token=api_token,
                    deployment_created=record["deployment_created"],
                )
                session.add(new_record)
                await session.commit()

        except IntegrityError as e:
            await session.rollback()

            # Check if the error specifically occurred due to the unique constraint on the detector_id column.
            # If it did, then we can ignore the error.
            # if "detector_id" in str(e.orig):

            if "detector_id" in str(e.orig):
                logger.debug(f"Detector ID {record['detector_id']} already exists in the database.")

                detectors = await self.query_detector_deployments(detector_id=record["detector_id"])
                if detectors is None or len(detectors) != 1:
                    raise AssertionError("Expected exactly one detector to be returned.")

                existing_api_token = detectors[0]["api_token"]

                if existing_api_token != api_token:
                    logger.info(f"Updating API token for detector ID {record['detector_id']}.")
                    await self.update_detector_deployment_record(detector_id=record["detector_id"], new_record=record)

            else:
                raise e

    async def update_detector_deployment_record(self, detector_id: str, new_record: Dict[str, str]) -> None:
        """
        Update the record for the given detector.
        :param detector_id: Detector ID
        :type detector_id: str

        :param new_record: A dictionary containing the new values for the record. This is expected to be
        a subset of the fields in the `detector_deployments` table.
        :type new_record: Dict[str, str]

        :return: None
        :rtype: None
        """

        if not new_record:
            return

        try:
            async with self.session() as session:
                query = select(self.DetectorDeployment).filter_by(detector_id=detector_id)
                result = await session.execute(query)

                detector_record = result.scalar_one_or_none()
                if detector_record is None:
                    return

                detector_record.api_token = new_record.get("api_token", detector_record.api_token)
                detector_record.deployment_created = new_record.get(
                    "deployment_created", detector_record.deployment_created
                )
                await session.commit()

        except IntegrityError:
            await session.rollback()
            logger.debug(f"Error occured while updating database record for {detector_id=}.", exc_info=True)

    async def query_detector_deployments(self, **kwargs) -> List[Dict[str, str]] | None:
        """
        Query the database table for detectors based on a given query predicate.
        :param kwargs: A dictionary containing the query predicate.
        :throws AttributeError: If the query predicate is invalid.
        """
        try:
            async with self.session() as session:
                query = select(
                    self.DetectorDeployment.detector_id,
                    self.DetectorDeployment.api_token,
                    self.DetectorDeployment.deployment_created,
                ).filter_by(**kwargs)
                query_results: List[Tuple] = await session.execute(query)
                query_results: List[Tuple] = query_results.fetchall()
                if not query_results:
                    return None

                detectors = [
                    {
                        "detector_id": row[0],
                        "api_token": row[1],
                        "deployment_created": row[2],
                    }
                    for row in query_results
                ]
                return detectors

        except SQLAlchemyError as e:
            logger.error("Error occured while querying database.", exc_info=True)
            raise e

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
                raise e

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

    async def create_tables(self) -> None:
        """
        Create the database tables if they don't exist.
        `Base.metadata.create_all` will create tables from all classes that inherit from `Base`.
        If the tables already exist, this will do nothing.
        :return: None
        :rtype: None
        """
        try:
            async with self._engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
        except SQLAlchemyError as e:
            logger.error("Could not create database tables.", exc_info=True)
            raise e

    async def on_shutdown(self) -> None:
        """
        This ensures that we release the resources.
        """
        await self._engine.dispose()
