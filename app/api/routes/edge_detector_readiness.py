from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends

from app.core.app_state import AppState, get_app_state
from app.core.edge_config_manager import EdgeConfigManager

router = APIRouter()

# Probes are tiny blocking GETs, so one thread per detector up to this cap keeps latency near a single probe's.
READINESS_PROBE_MAX_WORKERS = 64


@router.get("")
def get_edge_detector_readiness(app_state: AppState = Depends(get_app_state)):
    """Return readiness status for each configured detector.

    Checks whether the primary inference pod (and OODD pod, if applicable) for each
    detector is responding to health checks. Probes run concurrently so latency does
    not grow with the number of detectors; clients such as the SDK's `set_config`
    poll this with a short timeout.
    """
    config = EdgeConfigManager.active()
    detector_ids = [d.detector_id for d in config.detectors]
    if not detector_ids:
        return {}
    max_workers = min(READINESS_PROBE_MAX_WORKERS, len(detector_ids))
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="readiness-probe") as pool:
        results = pool.map(app_state.edge_inference_manager.inference_is_available, detector_ids)
        return {did: {"ready": ready} for did, ready in zip(detector_ids, results)}
