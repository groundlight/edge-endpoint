import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.app_state import AppState, get_app_state
from app.core.configs import RootEdgeConfig
from app.core.edge_config_loader import get_detector_inference_configs, save_runtime_edge_config
from app.core.edge_inference import get_edge_inference_model_name, get_edge_inference_service_name

logger = logging.getLogger(__name__)

router = APIRouter()


def _merge_config(existing: RootEdgeConfig, incoming: dict) -> RootEdgeConfig:
    """Merge incoming config dict into the existing RootEdgeConfig, returning a new validated config."""
    merged = existing.model_dump()

    if "global_config" in incoming:
        merged["global_config"].update(incoming["global_config"])

    if "edge_inference_configs" in incoming:
        for name, cfg in incoming["edge_inference_configs"].items():
            if name in merged["edge_inference_configs"]:
                merged["edge_inference_configs"][name].update(cfg)
            else:
                merged["edge_inference_configs"][name] = cfg

    if "detectors" in incoming:
        for det in incoming["detectors"]:
            det_id = det["detector_id"]
            merged["detectors"][det_id] = det

    return RootEdgeConfig(**merged)


def _apply_config(app_state: AppState, new_config: RootEdgeConfig, api_token: str) -> None:
    """Apply a new RootEdgeConfig to the app state, updating the inference manager
    and writing database records so the model updater discovers new detectors.
    """
    old_detector_ids = set(app_state.edge_config.detectors.keys())
    app_state.edge_config = new_config

    resolved = get_detector_inference_configs(new_config)
    if resolved is None:
        return

    manager = app_state.edge_inference_manager
    manager.detector_inference_configs = resolved

    for det_id, det_config in resolved.items():
        # Set api_token so the model updater can fetch models
        if det_config.api_token is None:
            det_config.api_token = api_token

        if det_config.enabled and det_id not in manager.inference_client_urls:
            manager.inference_client_urls[det_id] = get_edge_inference_service_name(det_id) + ":8000"
            if manager.separate_oodd_inference:
                manager.oodd_inference_client_urls[det_id] = (
                    get_edge_inference_service_name(det_id, is_oodd=True) + ":8000"
                )

        if det_id not in manager.last_escalation_times:
            manager.last_escalation_times[det_id] = None
        manager.min_times_between_escalations[det_id] = det_config.min_time_between_escalations

    # Write database records for new detectors so the model_updater (separate container)
    # discovers them and creates inference deployments.
    new_detector_ids = set(new_config.detectors.keys()) - old_detector_ids
    for det_id in new_detector_ids:
        primary_model_name = get_edge_inference_model_name(detector_id=det_id, is_oodd=False)
        app_state.db_manager.create_or_update_inference_deployment_record(
            deployment={
                "model_name": primary_model_name,
                "detector_id": det_id,
                "api_token": api_token,
                "deployment_created": False,
            }
        )
        if app_state.separate_oodd_inference:
            oodd_model_name = get_edge_inference_model_name(detector_id=det_id, is_oodd=True)
            app_state.db_manager.create_or_update_inference_deployment_record(
                deployment={
                    "model_name": oodd_model_name,
                    "detector_id": det_id,
                    "api_token": api_token,
                    "deployment_created": False,
                }
            )
        logger.info(f"Wrote deployment record for new detector {det_id}")


@router.post("")
async def post_edge_config(request: Request, app_state: AppState = Depends(get_app_state)):
    api_token = request.headers.get("x-api-token")
    if not api_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing x-api-token header")

    incoming = await request.json()
    logger.info(f"Received edge config from token={api_token[:8]}...: {incoming}")

    try:
        new_config = _merge_config(app_state.edge_config, incoming)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid config: {e}") from e

    _apply_config(app_state, new_config, api_token)
    save_runtime_edge_config(new_config)
    logger.info(f"Applied edge config update. edge_config={app_state.edge_config}")

    return {"status": "ok"}
