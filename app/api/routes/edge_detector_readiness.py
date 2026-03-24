import logging

from fastapi import APIRouter

from app.core.edge_config_loader import load_active_config
from app.core.edge_inference import get_edge_inference_service_name, is_edge_inference_ready

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("")
async def get_edge_detector_readiness():
    """Return readiness status for each configured detector.

    Checks whether the inference pod (and OODD pod) for each detector
    is responding to health checks.
    """
    config = load_active_config()
    detector_ids = [d.detector_id for d in config.detectors if d.detector_id]

    result = {}
    for detector_id in detector_ids:
        primary_ready = is_edge_inference_ready(get_edge_inference_service_name(detector_id) + ":8000")
        oodd_ready = is_edge_inference_ready(get_edge_inference_service_name(detector_id, is_oodd=True) + ":8000")
        result[detector_id] = {"ready": primary_ready and oodd_ready}

    return result
