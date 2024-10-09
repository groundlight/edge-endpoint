import json
import logging
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, Sequence

from model import ImageQuery
from sqlalchemy import create_engine, select
from sqlalchemy.engine.base import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.file_paths import DATABASE_FILEPATH, DATABASE_ORM_LOG_FILE, DATABASE_ORM_LOG_FILE_SIZE
from app.core.models import Base, ImageQueryEdge, InferenceDeployment

logger = logging.getLogger(__name__)


def get_database_url() -> str:
    """convenient function to mock for testing"""
    return f"sqlite:///{DATABASE_FILEPATH}"


class DatabaseManager:
    """
    Helper class for CRUD operations on the database.
    """

    def __init__(self, verbose: bool = False) -> None:
        """
        Initializes the database engine which manages creating and closing connection pools.
        :param verbose: If True, it will log all executed database queries.
        """
        log_level = logging.DEBUG if verbose else logging.INFO
        self._setup_logging(level=log_level)

        db_url = get_database_url()
        self._engine: Engine = create_engine(db_url, echo=verbose)

        # Factory for creating new Session objects.
        # A session is a mutable, stateful object that represents a single database transaction in progress.
        self.session_maker = sessionmaker(bind=self._engine)

    def _setup_logging(self, level: str | int) -> None:
        """
        Configures logging for SQLAlchemy. This is just so we can declutter the logs.
        Logs from the database will be written to the file specified by `DATABASE_ORM_LOG_FILE`.
        :param level: The logging level.
        """
        # configure SQLAlchemy logging
        sqlalchemy_logger = logging.getLogger("sqlalchemy.engine")
        sqlalchemy_logger.setLevel(level)

        file_handler = RotatingFileHandler(DATABASE_ORM_LOG_FILE, maxBytes=DATABASE_ORM_LOG_FILE_SIZE, backupCount=1)
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        file_handler.setFormatter(formatter)
        sqlalchemy_logger.addHandler(file_handler)

        # Ensure that other handlers do not propagate here
        sqlalchemy_logger.propagate = False

    def create_inference_deployment_record(self, deployment: Dict[str, str]) -> None:
        """
        Creates a new record in the `inference_deployments` table. If the record exists, but the API token has
        changed, we will update the record with the new API token.
        :param deployment: A dictionary containing the deployment details.

        TODO: Use a pydantic model for the record - see sqlmodels library
        """
        try:
            with self.session_maker() as session:
                session.add(InferenceDeployment(**deployment))
                session.commit()
        except IntegrityError as e:
            if "detector_id" not in str(e.orig):
                raise e
            self._handle_existing_detector(deployment)

    def _handle_existing_detector(self, deployment: Dict[str, str]) -> None:
        """
        Handles the case where a detector with the same ID already exists in the database.
        If the API token has changed, it updates the record with the new API token.
        :param deployment: A dictionary containing the deployment details.
        """
        logger.debug(f"Detector ID {deployment['detector_id']} already exists in the database.")
        detectors = self.get_inference_deployment_records(detector_id=deployment["detector_id"])
        if len(detectors) != 1:
            raise AssertionError("Expected exactly one detector to be returned.")

        existing_api_token = detectors[0].api_token
        if existing_api_token != deployment["api_token"]:  # type: ignore
            logger.info(f"Updating API token for detector ID {deployment['detector_id']}.")
            self.update_inference_deployment_record(detector_id=deployment["detector_id"], fields_to_update=deployment)

    def update_inference_deployment_record(self, detector_id: str, fields_to_update: Dict[str, Any]):
        """
        Update the record for the given detector.
        :param detector_id: Detector ID
        :param fields_to_update: A dictionary fields in the deployment record to update.
        """
        with self.session_maker() as session:
            query = select(InferenceDeployment).filter_by(detector_id=detector_id)
            result = session.execute(query)

            detector_record = result.scalar_one_or_none()
            if detector_record is None:
                return

            for field, value in fields_to_update.items():
                if hasattr(detector_record, field):
                    setattr(detector_record, field, value)
            session.commit()

    def get_inference_deployment_records(self, **kwargs) -> Sequence[InferenceDeployment]:
        """
        Query the database table for detectors based on a given query predicate.
        :param kwargs: A dictionary containing the query predicate.
        """
        with self.session_maker() as session:
            query = select(InferenceDeployment).filter_by(**kwargs)
            query_results = session.execute(query)
            return query_results.scalars().all()

    def delete_inference_deployment_records(self) -> None:
        """Delete all records in the `inference_deployments` table."""
        with self.session_maker() as session:
            session.query(InferenceDeployment).delete()
            session.commit()

    def create_iqe_record(self, iq: ImageQuery) -> None:
        """
        Creates a new record in the `image_queries_edge` table.
        :param iq: A image query to create an iqe record for.
        """
        with self.session_maker() as session:
            image_query_json = json.loads(iq.model_dump_json())
            session.add(ImageQueryEdge(image_query_id=iq.id, image_query=image_query_json))
            session.commit()

    def get_iqe_record(self, image_query_id: str) -> ImageQuery | None:
        """
        Gets a record from the `image_queries_edge` table.
        :param image_query_id: The ID of the image query.
        """
        with self.session_maker() as session:
            query = select(ImageQueryEdge.image_query).filter_by(image_query_id=image_query_id)
            result = session.execute(query)
            result_row: dict | None = result.scalar_one_or_none()
            if result_row is None:
                return None
            return ImageQuery(**result_row)

    def create_tables(self) -> None:
        """Create the database tables, if they don't already exist."""
        with self._engine.begin() as connection:
            Base.metadata.create_all(connection)

    def shutdown(self) -> None:
        self._engine.dispose()
