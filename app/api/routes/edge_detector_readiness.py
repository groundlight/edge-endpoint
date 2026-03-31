import logging

from fastapi import APIRouter, Depends

from app.core.app_state import AppState, get_app_state
from app.core.edge_config_manager import EdgeConfigManager

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("")
async def get_edge_detector_readiness(app_state: AppState = Depends(get_app_state)):
    """Return readiness status for each configured detector.

    Checks whether the inference pod (and OODD pod, if applicable) for each
    detector is responding to health checks.
    """
    config = EdgeConfigManager.active()
    detector_ids = [d.detector_id for d in config.detectors if d.detector_id]
    return {
        did: {"ready": app_state.edge_inference_manager.inference_is_available(did)}
        for did in detector_ids
    }
