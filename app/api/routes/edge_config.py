import logging
import os

from fastapi import APIRouter, Body, Depends
from groundlight.edge import EdgeEndpointConfig

from app.core.app_state import AppState, get_app_state
from app.core.edge_config_loader import get_detector_inference_configs
from app.core.edge_inference import EdgeInferenceManager, get_edge_inference_model_name

logger = logging.getLogger(__name__)

GROUNDLIGHT_API_TOKEN = os.environ.get("GROUNDLIGHT_API_TOKEN", "")

router = APIRouter()


@router.get("")
async def get_edge_config(app_state: AppState = Depends(get_app_state)):
    """Returns the currently active edge endpoint configuration."""
    return app_state.edge_config.to_payload()


@router.put("")
async def set_edge_config(
    body: dict = Body(...),
    app_state: AppState = Depends(get_app_state),
):
    """Replace the active edge endpoint configuration."""
    new_config = EdgeEndpointConfig.from_payload(body)
    old_config = app_state.edge_config

    old_detector_ids = {d.detector_id for d in old_config.detectors if d.detector_id}
    new_detector_ids = {d.detector_id for d in new_config.detectors if d.detector_id}
    removed = old_detector_ids - new_detector_ids
    added = new_detector_ids - old_detector_ids

    api_token = GROUNDLIGHT_API_TOKEN

    for detector_id in removed:
        logger.info(f"Marking detector {detector_id} for deletion")
        app_state.db_manager.mark_detector_pending_deletion(detector_id, api_token)

    for detector_id in added:
        logger.info(f"Creating deployment record for new detector {detector_id}")
        for is_oodd in [False, True]:
            model_name = get_edge_inference_model_name(detector_id, is_oodd=is_oodd)
            app_state.db_manager.create_or_update_inference_deployment_record(
                deployment={
                    "model_name": model_name,
                    "detector_id": detector_id,
                    "api_token": api_token,
                    "deployment_created": False,
                }
            )
            # Clear any stale pending_deletion flag from a previous config change
            app_state.db_manager.update_inference_deployment_record(
                model_name=model_name,
                fields_to_update={"pending_deletion": False, "deployment_created": False},
            )

    # Update in-memory state
    app_state.edge_config = new_config
    detector_inference_configs = get_detector_inference_configs(root_edge_config=new_config)
    app_state.edge_inference_manager = EdgeInferenceManager(
        detector_inference_configs=detector_inference_configs,
        separate_oodd_inference=app_state.separate_oodd_inference,
    )

    logger.info(f"Edge config updated: {len(removed)} detector(s) removed, {len(added)} detector(s) added")
    return new_config.to_payload()
