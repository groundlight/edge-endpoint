import datetime
import logging

from sqlalchemy import JSON, Boolean, Column, DateTime, String
from sqlalchemy.orm import declarative_base

logger = logging.getLogger(__name__)
Base = declarative_base()


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
        comment=("Indicates whether the given detector already has an inference deployment in the kubernetes cluster."),
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


class ImageQueryEdge(Base):
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
