import datetime
import json
import logging
from typing import Dict, List, Tuple

from logging.handlers import RotatingFileHandler
from model import ImageQuery
from sqlalchemy import JSON, Boolean, Column, DateTime, String, create_engine, select
from sqlalchemy.engine.base import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base, sessionmaker

from .file_paths import DATABASE_FILEPATH, DATABASE_ORM_LOG_FILE, DATABASE_ORM_LOG_FILE_SIZE

logger = logging.getLogger(__name__)
Base = declarative_base()


class DatabaseManager:
    class InferenceDeployment(Base):
        """
        Schema for the the `inference_deployments` database table.
        This is used by both the `edge-endpoint` and `inference-model-updater` containers.

        - The `edge-endpoint` container uses this table to add new detector ID's for which
        kubernetes deployments need to be created.
        - The `inference-model-updater` container uses it to create inference deployments for
        new detectors.

        """

        __tablename__ = "inference_deployments"
        detector_id = Column(String(44), primary_key=True, unique=True, nullable=False, comment="Detector ID")

        api_token = Column(String(66), nullable=False, comment="API token")
        deployment_created = Column(
            Boolean,
            default=False,
            nullable=False,
            comment=(
                "Indicates whether the given detector already has an inference deployment in the kubernetes cluster."
            ),
        )
        deployment_name = Column(
            String(100),
            nullable=True,
            comment="Name of the kubernetes deployment for the inference server.",
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

    class ImageQueriesEdge(Base):
        """
        Schema for the `image_queries_edge` database table.
        This table is used  by the `edge-endpoint` container to store image queries created from the
        `POST /image-queries` endpoint on the edge.

        This is necessary because the core Groundlight service does not recognize these image queries.
        Storing them in this table allows us to properly handle `GET /image-queries/{image_query_id}` on the edge.

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

    def __init__(self, verbose: bool = False) -> None:
        """
        Initializes the database engine which manages creating and closing connection pools.
        :param verbose: If True, it will log all executed database queries.
        """

        log_level = logging.DEBUG if verbose else logging.INFO
        self._setup_logging(level=log_level)

        db_url = f"sqlite:///{DATABASE_FILEPATH}"
        self._engine: Engine = create_engine(db_url, echo=verbose)

        # Factory for creating new Session objects.
        # A session is a mutable, stateful object that represents a single database transaction in progress.
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

    def create_inference_deployment_record(self, record: Dict[str, str]) -> None:
        """
        Creates a new record in the `inference_deployments` table. If the record exists, but the API token has
        changed, we will update the record with the new API token.
        :param record: A dictionary containing a subset of the fields in the `inference_deployments` table.

        TODO: Use a pydantic model for the record.
        """
        api_token = record["api_token"]
        try:
            with self.session_maker() as session:
                new_record = self.InferenceDeployment(**record)
                session.add(new_record)
                session.commit()

        except IntegrityError as e:
            # Check if the error specifically occurred due to the unique constraint on the detector_id column.
            # If it did, then we can ignore the error.

            if "detector_id" in str(e.orig):
                logger.debug(f"Detector ID {record['detector_id']} already exists in the database.")

                detectors = self.query_inference_deployments(detector_id=record["detector_id"])
                if len(detectors) != 1:
                    raise AssertionError("Expected exactly one detector to be returned.")

                existing_api_token = detectors[0].api_token

                if existing_api_token != api_token:
                    logger.info(f"Updating API token for detector ID {record['detector_id']}.")
                    self.update_inference_deployment_record(detector_id=record["detector_id"], new_record=record)

            else:
                raise e

    def update_inference_deployment_record(self, detector_id: str, new_record: Dict[str, str]) -> None:
        """
        Update the record for the given detector.
        :param detector_id: Detector ID
        :param new_record: A dictionary containing the new values for the record. This is expected to be
        a subset of the fields in the `inference_deployments` table.
        """

        if not new_record:
            return

        with self.session_maker() as session:
            query = select(self.InferenceDeployment).filter_by(detector_id=detector_id)
            result = session.execute(query)

            detector_record = result.scalar_one_or_none()
            if detector_record is None:
                return

            for field, value in new_record.items():
                if hasattr(detector_record, field):
                    setattr(detector_record, field, value)
            session.commit()

    def query_inference_deployments(self, **kwargs) -> List[InferenceDeployment]:
        """
        Query the database table for detectors based on a given query predicate.
        :param kwargs: A dictionary containing the query predicate.
        """
        with self.session_maker() as session:
            query = select(self.InferenceDeployment).filter_by(**kwargs)
            query_results = session.execute(query)
            query_results = query_results.fetchall()

            # SQLAlchemy returns single element tuples for each query result.
            query_results = [result[0] for result in query_results]
            return query_results

    def create_iqe_record(self, record: ImageQuery) -> None:
        """
        Creates a new record in the `image_queries_edge` table.
        :param record: A image query .
        """
        with self.session_maker() as session:
            image_query_id = record.id
            image_query_json = json.loads(record.json())

            new_record = self.ImageQueriesEdge(
                image_query_id=image_query_id,
                image_query=image_query_json,
            )
            session.add(new_record)
            session.commit()

    def get_iqe_record(self, image_query_id: str) -> ImageQuery | None:
        """
        Gets a record from the `image_queries_edge` table.
        :param image_query_id: The ID of the image query.
        """
        with self.session_maker() as session:
            query = select(self.ImageQueriesEdge.image_query).filter_by(image_query_id=image_query_id)
            result = session.execute(query)
            result_row: dict | None = result.scalar_one_or_none()
            if result_row is None:
                return None

            return ImageQuery(**result_row)

    def create_tables(self) -> None:
        """
        Create the database tables if they don't exist.
        `Base.metadata.create_all` will create tables from all classes that inherit from `Base`.
        If the tables already exist, this will do nothing.
        """
        with self._engine.begin() as connection:
            Base.metadata.create_all(connection)

    def shutdown(self) -> None:
        """
        This ensures that we release the resources.
        """
        self._engine.dispose()
