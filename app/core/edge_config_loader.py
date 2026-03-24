import logging
import os
from typing import Dict

import yaml
from groundlight.edge import EdgeEndpointConfig, InferenceConfig

from .database import DatabaseManager
from .edge_inference import get_edge_inference_model_name
from .file_paths import ACTIVE_EDGE_CONFIG_PATH, HELM_EDGE_CONFIG_PATH

logger = logging.getLogger(__name__)

GROUNDLIGHT_API_TOKEN = os.environ.get("GROUNDLIGHT_API_TOKEN", "")


def load_edge_config() -> EdgeEndpointConfig:
    """Load edge config at startup."""
    yaml_config = os.environ.get("EDGE_CONFIG", "").strip()
    if yaml_config:
        return EdgeEndpointConfig.from_yaml(yaml_str=yaml_config)
    if os.path.exists(HELM_EDGE_CONFIG_PATH):
        return EdgeEndpointConfig.from_yaml(filename=HELM_EDGE_CONFIG_PATH)
    if os.path.exists(ACTIVE_EDGE_CONFIG_PATH):
        return EdgeEndpointConfig.from_yaml(filename=ACTIVE_EDGE_CONFIG_PATH)
    return EdgeEndpointConfig()


def save_active_config(config: EdgeEndpointConfig) -> None:
    """Write the active config to disk."""
    os.makedirs(os.path.dirname(ACTIVE_EDGE_CONFIG_PATH), exist_ok=True)
    with open(ACTIVE_EDGE_CONFIG_PATH, "w") as f:
        yaml.dump(config.to_payload(), f, default_flow_style=False)


def get_refresh_rate() -> float:
    """Return the current refresh_rate from the active config file."""
    return load_active_config().global_config.refresh_rate


def load_active_config() -> EdgeEndpointConfig:
    """Read the active config from disk, falling back to Pydantic defaults."""
    if os.path.exists(ACTIVE_EDGE_CONFIG_PATH):
        return EdgeEndpointConfig.from_yaml(filename=ACTIVE_EDGE_CONFIG_PATH)
    return EdgeEndpointConfig()


def get_active_detector_ids(db_manager: DatabaseManager) -> set[str]:
    """Return detector IDs from the DB that are not pending deletion."""
    all_records = db_manager.get_inference_deployment_records()
    return {r.detector_id for r in all_records if not r.pending_deletion}


def apply_detector_changes(removed: set[str], added: set[str], db_manager: DatabaseManager) -> None:
    """Mark removed detectors for deletion and create DB records for added ones."""
    for detector_id in removed:
        logger.info(f"Marking detector {detector_id} for deletion")
        db_manager.mark_detector_pending_deletion(detector_id)

    for detector_id in added:
        logger.info(f"Creating deployment record for new detector {detector_id}")
        for is_oodd in [False, True]:
            model_name = get_edge_inference_model_name(detector_id, is_oodd=is_oodd)
            db_manager.create_or_update_inference_deployment_record(
                deployment={
                    "model_name": model_name,
                    "detector_id": detector_id,
                    "api_token": GROUNDLIGHT_API_TOKEN,
                    "deployment_created": False,
                    "pending_deletion": False,
                }
            )


def compute_detector_diff(current_detector_ids: set[str], new_config: EdgeEndpointConfig) -> tuple[set[str], set[str]]:
    """Compute which detectors to remove and add.

    Returns (removed_ids, added_ids).
    """
    desired = {d.detector_id for d in new_config.detectors if d.detector_id}
    return current_detector_ids - desired, desired - current_detector_ids


def reconcile_config(new_config: EdgeEndpointConfig, db_manager: DatabaseManager) -> None:
    """
    Compute the diff between a provided config and the DB state. Apply the new config. Write the new
    config to disk.
    """
    current = get_active_detector_ids(db_manager)
    removed, added = compute_detector_diff(current, new_config)

    apply_detector_changes(removed, added, db_manager)
    save_active_config(new_config)
    logger.info(
        f"Config reconciled: {len(removed)} detector(s) removed, {len(added)} detector(s) added. "
        f"Removed detectors: {removed} | Added detectors: {added}"
    )


def get_detector_inference_configs(
    edge_endpoint_config: EdgeEndpointConfig,
) -> dict[str, InferenceConfig] | None:
    """
    Produces a dict mapping detector IDs to their associated `InferenceConfig`.
    Returns None if there are no detectors in the config file.
    """
    # Mapping of config names to InferenceConfig objects
    edge_inference_configs: dict[str, InferenceConfig] = edge_endpoint_config.edge_inference_configs

    # Filter out detectors whose IDs are empty strings.
    detectors = [detector for detector in edge_endpoint_config.detectors if detector.detector_id != ""]

    detector_to_inference_config: dict[str, InferenceConfig] | None = None
    if detectors:
        detector_to_inference_config = {
            detector.detector_id: edge_inference_configs[detector.edge_inference_config] for detector in detectors
        }

    return detector_to_inference_config


def get_detector_edge_configs_by_id() -> Dict[str, InferenceConfig]:
    """
    Convenience helper that loads the active edge config and returns detector-level inference configs,
    defaulting to an empty dict when none are defined.
    """
    active_config = load_active_config()
    detector_configs = get_detector_inference_configs(active_config)
    return detector_configs or {}
