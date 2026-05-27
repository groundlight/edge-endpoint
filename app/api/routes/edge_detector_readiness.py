from fastapi import APIRouter, Depends

from app.core.app_state import AppState, get_app_state
from app.core.edge_config_manager import EdgeConfigManager
from app.core.edge_inference import check_inference_ready

router = APIRouter()


@router.get("")
async def get_edge_detector_readiness(app_state: AppState = Depends(get_app_state)):
    """Return readiness status for each configured detector.

    Checks whether the primary inference pod (and OODD pod, if applicable) for each
    detector is responding to health checks.
    """
    config = EdgeConfigManager.active()
    detector_ids = [d.detector_id for d in config.detectors]
    return {did: {"ready": check_inference_ready(did, app_state.separate_oodd_inference)} for did in detector_ids}
