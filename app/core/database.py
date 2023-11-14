import datetime
import json
import logging
from logging.handlers import RotatingFileHandler
import re
from typing import Dict, List, Tuple

from model import ImageQuery
from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, select, create_engine
from sqlalchemy.engine.base import Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
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

        api_token = Column(String(44), nullable=False, comment="API token")
        deployment_created = Column(
            Boolean,
            default=False,
            nullable=False,
            comment=(
                "Indicates whether the given detector already has an inference deployment in the kubernetes cluster."
            ),
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
        This table is used  by the `edge-endpoint` container to store image queries created from the
        `POST /image-queries` endpoint on the edge.

        This is necessary because the core Groundlight service currently does not recognize these image queries.
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

        @validates("image_query_id")
        def validate_uid(self, key, value):
            validate_uid(value)
            return value

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
        # A session is a mutable, stateful object that represents a single database
        # transaction in progress.
        self.session_maker = sessionmaker(bind=self._engine)

    def _setup_logging(self, level) -> None:
        """
        Configures logging for SQLAlchemy. This is just so we can declutter the logs.
        Logs from the database will be written to the file specified by `DATABASE_ORM_LOG_FILE`.
        """
        # configure SQLAlchemy logging
        sqlalchemy_logger = logging.getLogger("sqlalchemy.engine")
        sqlalchemy_logger.setLevel(level)

        file_handler = RotatingFileHandler(DATABASE_ORM_LOG_FILE, maxBytes=10_000_000, backupCount=10)
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        file_handler.setFormatter(formatter)
        sqlalchemy_logger.addHandler(file_handler)

        # Ensure that other handlers do not propagate here
        sqlalchemy_logger.propagate = False

    def create_inference_deployment_record(self, record: Dict[str, str]) -> None:
        """
        Creates a new record in the `inference_deployments` table. If the record exists, but the API token has
        changed, we will update the record with the new API token.
        :param record: A dictionary containing the detector_id, api_token, and deployment_created fields.
        :type record: Dict[str, str]

        :return: None
        :rtype: None
        """
        api_token = record["api_token"]
        try:
            with self.session_maker() as session:
                new_record = self.InferenceDeployment(
                    detector_id=record["detector_id"],
                    api_token=api_token,
                    deployment_created=record["deployment_created"],
                )
                session.add(new_record)
                session.commit()

        except IntegrityError as e:
            # Check if the error specifically occurred due to the unique constraint on the detector_id column.
            # If it did, then we can ignore the error.

            if "detector_id" in str(e.orig):
                logger.debug(f"Detector ID {record['detector_id']} already exists in the database.")

                detectors = self.query_inference_deployments(detector_id=record["detector_id"])
                if detectors is None or len(detectors) != 1:
                    raise AssertionError("Expected exactly one detector to be returned.")

                existing_api_token = detectors[0]["api_token"]

                if existing_api_token != api_token:
                    logger.info(f"Updating API token for detector ID {record['detector_id']}.")
                    self.update_inference_deployment_record(detector_id=record["detector_id"], new_record=record)

            else:
                raise e

    def update_inference_deployment_record(self, detector_id: str, new_record: Dict[str, str]) -> None:
        """
        Update the record for the given detector.
        :param detector_id: Detector ID
        :type detector_id: str

        :param new_record: A dictionary containing the new values for the record. This is expected to be
        a subset of the fields in the `inference_deployments` table.
        :type new_record: Dict[str, str]

        :return: None
        :rtype: None
        """

        if not new_record:
            return

        with self.session_maker() as session:
            query = select(self.InferenceDeployment).filter_by(detector_id=detector_id)
            result = session.execute(query)

            detector_record = result.scalar_one_or_none()
            if detector_record is None:
                return

            detector_record.api_token = new_record.get("api_token", detector_record.api_token)
            detector_record.deployment_created = new_record.get(
                "deployment_created", detector_record.deployment_created
            )
            session.commit()

    def query_inference_deployments(self, **kwargs) -> List[Dict[str, str]] | None:
        """
        Query the database table for detectors based on a given query predicate.
        :param kwargs: A dictionary containing the query predicate.
        """
        with self.session_maker() as session:
            query = select(
                self.InferenceDeployment.detector_id,
                self.InferenceDeployment.api_token,
                self.InferenceDeployment.deployment_created,
            ).filter_by(**kwargs)
            query_results: List[Tuple] = session.execute(query)
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

    def create_iqe_record(self, record: ImageQuery) -> None:
        """
        Creates a new record in the `image_queries_edge` table.
        :param record: A image query .
        :type record: ImageQuery

        :return: None
        :rtype: None
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
        :type image_query_id: str

        :return: The image query record.
        :rtype: ImageQuery | None
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
        :return: None
        :rtype: None
        """
        with self._engine.begin() as connection:
            Base.metadata.create_all(connection)

    def shutdown(self) -> None:
        """
        This ensures that we release the resources.
        """
        self._engine.dispose()
