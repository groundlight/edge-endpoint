import json
import logging
from logging.handlers import RotatingFileHandler
from typing import Sequence

from model import ImageQuery
from sqlalchemy import create_engine, select
from sqlalchemy.engine.base import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlmodel import SQLModel

from app.core.file_paths import DATABASE_FILEPATH, DATABASE_ORM_LOG_FILE, DATABASE_ORM_LOG_FILE_SIZE
from app.db.models import ImageQueryEdge, InferenceDeployment

logger = logging.getLogger(__name__)
Base = declarative_base()


class DatabaseManager:
    def __init__(self, engine: Engine, verbose: bool = False) -> None:
        """
        Initializes the database engine which manages creating and closing connection pools.
        :param verbose: If True, it will log all executed database queries.
        """
        log_level = logging.DEBUG if verbose else logging.INFO
        self._setup_logging(level=log_level)
        self._engine = engine
        self.session_maker = sessionmaker(bind=self._engine)

    def _setup_logging(self, level) -> None:
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

    def create_inference_deployment_record(self, deployment: InferenceDeployment) -> None:
        """
        Creates a new record in the `inference_deployments` table. If the record exists, but the API token has
        changed, we will update the record with the new API token.
        :param record: A dictionary containing a subset of the fields in the `inference_deployments` table.
        """
        try:
            with self.session_maker() as session:
                # HACK: annoyingly, we need to create sqlalchemy records within a session, so if they
                # are instantiated elsewhere, we need to re-instantiate them here via a copy.
                deployment = InferenceDeployment(**deployment.model_dump())
                session.add(deployment)
                session.commit()
        except IntegrityError as e:
            if "detector_id" in str(e.orig):
                logger.debug(f"Detector ID {deployment.detector_id} already exists.")
                self._handle_existing_deployment(deployment, deployment.api_token)
            else:
                raise e

    def _handle_existing_deployment(self, deployment: InferenceDeployment, api_token: str) -> None:
        detectors = self.query_inference_deployments(detector_id=deployment.detector_id)
        if len(detectors) != 1:
            raise AssertionError("Expected exactly one detector to be returned.")

        existing_api_token = detectors[0].api_token
        if existing_api_token != api_token:
            logger.info(f"Updating API token for detector ID {deployment.detector_id}.")
            self.update_inference_deployment_record(
                detector_id=deployment.detector_id, fields_to_update={"api_token": api_token}
            )

    def update_inference_deployment_record(self, detector_id: str, fields_to_update: dict[str, str] | None) -> None:
        """
        Update the record for the given detector.
        :param detector_id: Detector ID
        :param fields_to_update: A dictionary containing the new values for the record. This is expected to be
        a subset of the fields in the `inference_deployments` table.
        """
        if not fields_to_update:
            return

        with self.session_maker() as session:
            query = select(InferenceDeployment).filter_by(detector_id=detector_id)
            result = session.execute(query)
            detector_record = result.scalar_one_or_none()

            if detector_record is None:
                return  # No record found...

            for field, value in fields_to_update.items():
                setattr(detector_record, field, value)  # TODO: re-validate the record here

            try:
                session.commit()
            except Exception as e:
                logger.error(f"Failed to update record for detector ID {detector_id}: {e}")
                session.rollback()

    def query_inference_deployments(self, **kwargs) -> Sequence[InferenceDeployment]:
        """
        Query the database table for detectors based on a given query predicate.
        :param kwargs: A dictionary containing the query predicate.
        """
        with self.session_maker() as session:
            query = select(InferenceDeployment).filter_by(**kwargs)
            query_results = session.execute(query).scalars().fetchall()
            return query_results

    def create_iqe_record(self, iq: ImageQuery) -> None:
        """
        Creates a new record in the `image_queries_edge` table.
        :param record: A image query .
        """
        with self.session_maker() as session:
            record = ImageQueryEdge(image_query_id=iq.id, image_query=json.loads(iq.json()))
            session.add(record)
            session.commit()

    def get_iqe_record(self, image_query_id: str) -> ImageQuery | None:
        """
        Gets a record from the `image_queries_edge` table.
        :param image_query_id: The ID of the image query.
        """
        with self.session_maker() as session:
            query = select(ImageQueryEdge).filter_by(image_query_id=image_query_id)
            result = session.execute(query)
            iqe = result.scalar_one_or_none()
            if iqe is None:
                return None
            return ImageQuery.model_validate(iqe.image_query)

    def create_tables(self) -> None:
        """Create the database tables if they don't exist."""
        SQLModel.metadata.create_all(self._engine)


def get_database_engine() -> Engine:
    """Get the database engine. Easily mocked for testing."""
    db_url = f"sqlite:///{DATABASE_FILEPATH}"
    return create_engine(db_url)
