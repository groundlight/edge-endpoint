import json
import logging
from typing import Sequence

from model import ImageQuery
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.db.models import ImageQueryEdge, InferenceDeployment

logger = logging.getLogger(__name__)


def create_inference_deployment_record(db: Session, deployment: InferenceDeployment) -> None:
    """
    Creates a new record in the `inference_deployments` table. If the record exists, but the API token has
    changed, we will update the record with the new API token.
    :param record: A dictionary containing a subset of the fields in the `inference_deployments` table.
    """
    try:
        # HACK: annoyingly, we need to create sqlalchemy records within a session, so if they
        # are instantiated elsewhere, we need to re-instantiate them here via a copy.
        deployment = InferenceDeployment(**deployment.model_dump())
        db.add(deployment)
        db.commit()
    except IntegrityError as e:
        if "detector_id" in str(e.orig):
            logger.debug(f"Detector ID {deployment.detector_id} already exists.")
            _handle_existing_deployment(db, deployment, deployment.api_token)
        else:
            raise e


def _handle_existing_deployment(db: Session, deployment: InferenceDeployment, api_token: str) -> None:
    detectors = get_inference_deployments(db=db, detector_id=deployment.detector_id)
    if len(detectors) != 1:
        raise AssertionError("Expected exactly one detector to be returned.")

    existing_api_token = detectors[0].api_token
    if existing_api_token != api_token:
        logger.info(f"Updating API token for detector ID {deployment.detector_id}.")
        update_inference_deployment_record(
            db=db, detector_id=deployment.detector_id, fields_to_update={"api_token": api_token}
        )


def update_inference_deployment_record(db: Session, detector_id: str, fields_to_update: dict[str, str] | None) -> None:
    """
    Update the record for the given detector.
    :param detector_id: Detector ID
    :param fields_to_update: A dictionary containing the new values for the record. This is expected to be
    a subset of the fields in the `inference_deployments` table.
    """
    if not fields_to_update:
        return

    query = select(InferenceDeployment).filter_by(detector_id=detector_id)
    result = db.execute(query)
    detector_record = result.scalar_one_or_none()

    if detector_record is None:
        return  # No record found...

    for field, value in fields_to_update.items():
        setattr(detector_record, field, value)  # TODO: re-validate the record here

    try:
        db.commit()
    except Exception as e:
        logger.error(f"Failed to update record for detector ID {detector_id}: {e}")
        db.rollback()


def get_inference_deployments(db: Session, **kwargs) -> Sequence[InferenceDeployment]:
    """
    Query the database table for detectors based on a given query predicate.
    :param kwargs: A dictionary containing the query predicate.
    """
    query = select(InferenceDeployment).filter_by(**kwargs)
    query_results = db.execute(query).scalars().fetchall()
    return query_results


def create_iqe_record(db: Session, iq: ImageQuery) -> None:
    """
    Creates a new record in the `image_queries_edge` table.
    :param record: A image query .
    """
    record = ImageQueryEdge(image_query_id=iq.id, image_query=json.loads(iq.json()))
    db.add(record)
    db.commit()


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
