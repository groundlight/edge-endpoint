import logging
import os
import shutil
import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status

from app.core.app_state import AppState, get_app_state
from app.core.configs import RootEdgeConfig
from app.core.edge_config_loader import get_detector_inference_configs, save_runtime_edge_config
from app.core.edge_inference import get_edge_inference_model_name, get_edge_inference_service_name
from app.core.file_paths import MODEL_REPOSITORY_PATH

logger = logging.getLogger(__name__)

router = APIRouter()

DELETION_POLL_INTERVAL = 2
DELETION_TIMEOUT = 120


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


def _build_replace_config(incoming: dict) -> RootEdgeConfig:
    """Build a RootEdgeConfig from incoming dict for replace mode.
    Missing top-level sections get Pydantic defaults.
    """
    data = dict(incoming)
    data.setdefault("global_config", {})
    data.setdefault("edge_inference_configs", {})
    detectors = data.get("detectors", [])
    data["detectors"] = {det["detector_id"]: det for det in detectors}
    return RootEdgeConfig(**data)


def _apply_config(app_state: AppState, new_config: RootEdgeConfig, api_token: str) -> set[str]:
    """Apply a new RootEdgeConfig to the app state, updating the inference manager
    and writing database records so the model updater discovers new detectors.
    Returns the set of newly added detector IDs.
    """
    old_detector_ids = set(app_state.edge_config.detectors.keys())
    app_state.edge_config = new_config

    resolved = get_detector_inference_configs(new_config)
    if resolved is None:
        return set()

    manager = app_state.edge_inference_manager
    manager.detector_inference_configs = resolved

    for det_id, det_config in resolved.items():
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

    new_detector_ids = set(new_config.detectors.keys()) - old_detector_ids
    return new_detector_ids


def _write_new_detector_db_records(app_state: AppState, new_detector_ids: set[str], api_token: str) -> None:
    """Write DB records for new detectors so the model updater picks them up."""
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


def _remove_detectors(app_state: AppState, removed_ids: set[str]) -> None:
    """Delete K8s resources, DB records, and model files for removed detectors.
    Blocks until all pods are fully terminated before returning.
    """
    if not removed_ids or app_state.deployment_manager is None:
        return

    dm = app_state.deployment_manager
    manager = app_state.edge_inference_manager

    # Step 1: Delete K8s Deployments and Services
    for det_id in removed_ids:
        dm.delete_inference_deployment(det_id, is_oodd=False)
        if app_state.separate_oodd_inference:
            dm.delete_inference_deployment(det_id, is_oodd=True)

    # Step 2: Wait for all pods to fully terminate
    deadline = time.time() + DELETION_TIMEOUT
    while time.time() < deadline:
        all_gone = True
        for det_id in removed_ids:
            if not dm.is_detector_fully_removed(det_id, is_oodd=False):
                all_gone = False
                break
            if app_state.separate_oodd_inference and not dm.is_detector_fully_removed(det_id, is_oodd=True):
                all_gone = False
                break
        if all_gone:
            break
        time.sleep(DELETION_POLL_INTERVAL)
    else:
        logger.error(f"Timed out waiting for detector pods to terminate: {removed_ids}")

    # Step 3: Delete DB records
    for det_id in removed_ids:
        primary_model_name = get_edge_inference_model_name(detector_id=det_id, is_oodd=False)
        app_state.db_manager.delete_inference_deployment_record(primary_model_name)
        if app_state.separate_oodd_inference:
            oodd_model_name = get_edge_inference_model_name(detector_id=det_id, is_oodd=True)
            app_state.db_manager.delete_inference_deployment_record(oodd_model_name)

    # Step 4: Delete model files from disk
    for det_id in removed_ids:
        model_dir = os.path.join(MODEL_REPOSITORY_PATH, det_id)
        if os.path.isdir(model_dir):
            shutil.rmtree(model_dir)
            logger.info(f"Deleted model files at {model_dir}")

    # Step 5: Clean up in-memory state
    for det_id in removed_ids:
        manager.inference_client_urls.pop(det_id, None)
        manager.oodd_inference_client_urls.pop(det_id, None)
        manager.last_escalation_times.pop(det_id, None)
        manager.min_times_between_escalations.pop(det_id, None)

    logger.info(f"Finished removing detectors: {removed_ids}")


def _replace_config_background(
    app_state: AppState,
    removed_ids: set[str],
    new_detector_ids: set[str],
    api_token: str,
) -> None:
    """Background task: delete removed detectors (waiting for termination), then write
    DB records for new detectors so the model updater can create them.
    """
    try:
        _remove_detectors(app_state, removed_ids)
        _write_new_detector_db_records(app_state, new_detector_ids, api_token)
    except Exception:
        logger.exception("Error during replace config background task")


@router.post("")
async def post_edge_config(
    request: Request,
    background_tasks: BackgroundTasks,
    app_state: AppState = Depends(get_app_state),
):
    api_token = request.headers.get("x-api-token")
    if not api_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing x-api-token header")

    incoming = await request.json()
    replace = incoming.pop("replace", False)
    logger.info(f"Received edge config from token={api_token[:8]}... replace={replace}: {incoming}")

    old_detector_ids = set(app_state.edge_config.detectors.keys())

    try:
        if replace:
            new_config = _build_replace_config(incoming)
        else:
            new_config = _merge_config(app_state.edge_config, incoming)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid config: {e}") from e

    new_detector_ids = _apply_config(app_state, new_config, api_token)
    save_runtime_edge_config(new_config)

    if replace:
        removed_ids = old_detector_ids - set(new_config.detectors.keys())
        background_tasks.add_task(
            _replace_config_background, app_state, removed_ids, new_detector_ids, api_token
        )
        logger.info(
            f"Applied replace config. removing={removed_ids}, adding={new_detector_ids}. "
            "Deletion running in background."
        )
    else:
        _write_new_detector_db_records(app_state, new_detector_ids, api_token)
        logger.info(f"Applied merge config update. new_detectors={new_detector_ids}")

    return {"status": "ok", "removed": list(old_detector_ids - set(new_config.detectors.keys())) if replace else []}
