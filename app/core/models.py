import datetime
import logging

from sqlalchemy import Boolean, Column, DateTime, String
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
    deployment_name = Column(
        String(100),
        primary_key=True,
        unique=True,
        nullable=False,
        comment="Deployment name, Detector ID + `-primary` or `-oodd`",
    )

    api_token = Column(String(66), nullable=False, comment="API token")
    deployment_created = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="Indicates whether the given detector already has an inference deployment in the kubernetes cluster.",
    )
    detector_id = Column(
        String(44),
        nullable=True,
        comment="Detector ID",
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
