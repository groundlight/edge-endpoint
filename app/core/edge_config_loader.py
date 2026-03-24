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
    """Load edge config at startup, falling back to Pydantic defaults.

    Sources checked in order:
    1. EDGE_CONFIG env var (used by Docker tests and non-Helm setups)
    2. Helm-mounted ConfigMap file at HELM_EDGE_CONFIG_PATH
    3. EdgeEndpointConfig() Pydantic defaults

    # TODO: discuss whether Helm config should always overwrite the active
    # config file on restart, making set_edge_config changes ephemeral.
    """
    yaml_config = os.environ.get("EDGE_CONFIG", "").strip()
    if yaml_config:
        return EdgeEndpointConfig.from_yaml(yaml_str=yaml_config)
    if os.path.exists(HELM_EDGE_CONFIG_PATH):
        return EdgeEndpointConfig.from_yaml(filename=HELM_EDGE_CONFIG_PATH)
    return EdgeEndpointConfig()


def save_active_config(config: EdgeEndpointConfig) -> None:
    """Write the config to the shared PVC YAML file."""
    with open(ACTIVE_EDGE_CONFIG_PATH, "w") as f:
        yaml.dump(config.to_payload(), f, default_flow_style=False)


def load_active_config() -> EdgeEndpointConfig:
    """Read the active config from the PVC YAML file, falling back to Pydantic defaults."""
    if os.path.exists(ACTIVE_EDGE_CONFIG_PATH):
        return EdgeEndpointConfig.from_yaml(filename=ACTIVE_EDGE_CONFIG_PATH)
    return EdgeEndpointConfig()


def reconcile_config(new_config: EdgeEndpointConfig, db_manager: DatabaseManager) -> tuple[set[str], set[str]]:
    """Reconcile a new config against the DB and persist it to the PVC file.

    Diffs the new config's detectors against what's currently in the DB
    (excluding detectors already pending deletion), marks removed detectors
    for deletion, creates records for newly added detectors, and writes
    the config to the shared YAML file.

    This is the single code path used by both startup and PUT /edge-config.

    Returns (removed_ids, added_ids).
    """
    all_records = db_manager.get_inference_deployment_records()
    current_detector_ids = {r.detector_id for r in all_records if not r.pending_deletion}
    new_detector_ids = {d.detector_id for d in new_config.detectors if d.detector_id}

    removed = current_detector_ids - new_detector_ids
    added = new_detector_ids - current_detector_ids

    for detector_id in removed:
        logger.info(f"Marking detector {detector_id} for deletion")
        db_manager.mark_detector_pending_deletion(detector_id, GROUNDLIGHT_API_TOKEN)

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
                }
            )
            db_manager.update_inference_deployment_record(
                model_name=model_name,
                fields_to_update={"pending_deletion": False, "deployment_created": False},
            )

    save_active_config(new_config)
    logger.info(f"Config reconciled: {len(removed)} detector(s) removed, {len(added)} detector(s) added")
    return removed, added


def get_detector_inference_configs(
    root_edge_config: EdgeEndpointConfig,
) -> dict[str, InferenceConfig] | None:
    """
    Produces a dict mapping detector IDs to their associated `InferenceConfig`.
    Returns None if there are no detectors in the config file.
    """
    edge_inference_configs: dict[str, InferenceConfig] = root_edge_config.edge_inference_configs
    detectors = [detector for detector in root_edge_config.detectors if detector.detector_id != ""]

    detector_to_inference_config: dict[str, InferenceConfig] | None = None
    if detectors:
        detector_to_inference_config = {
            detector.detector_id: edge_inference_configs[detector.edge_inference_config] for detector in detectors
        }

    return detector_to_inference_config


def get_detector_edge_configs_by_id() -> Dict[str, InferenceConfig]:
    """
    Convenience helper that loads the edge config and returns detector-level inference configs,
    defaulting to an empty dict when none are defined.
    """
    root_config = load_edge_config()
    detector_configs = get_detector_inference_configs(root_config)
    return detector_configs or {}
