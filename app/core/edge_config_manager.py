import logging
import os

import yaml
from groundlight.edge import EdgeEndpointConfig, InferenceConfig

from .database import DatabaseManager
from .file_paths import ACTIVE_EDGE_CONFIG_PATH
from .naming import get_edge_inference_model_name

logger = logging.getLogger(__name__)

GROUNDLIGHT_API_TOKEN = os.environ.get("GROUNDLIGHT_API_TOKEN", "")


class EdgeConfigManager:
    """Manages the lifecycle of the edge endpoint configuration: saving and
    mtime-cached reading of the active config file on PVC."""

    _cached_config: EdgeEndpointConfig = EdgeEndpointConfig()
    _cached_mtime: float = 0.0

    @classmethod
    def save(cls, config: EdgeEndpointConfig) -> None:
        """Write the active config to disk."""
        os.makedirs(os.path.dirname(ACTIVE_EDGE_CONFIG_PATH), exist_ok=True)
        with open(ACTIVE_EDGE_CONFIG_PATH, "w") as f:
            yaml.dump(config.to_payload(), f, default_flow_style=False)

    @classmethod
    def active(cls) -> EdgeEndpointConfig:
        """Return the current active config, re-reading from disk only when the file changes."""
        try:
            mtime = os.path.getmtime(ACTIVE_EDGE_CONFIG_PATH)
        except FileNotFoundError:
            logger.debug("Active config file not yet available at %s, using defaults", ACTIVE_EDGE_CONFIG_PATH)
            return cls._cached_config
        if mtime != cls._cached_mtime:
            try:
                cls._cached_config = EdgeEndpointConfig.from_yaml(filename=ACTIVE_EDGE_CONFIG_PATH)
                cls._cached_mtime = mtime
            except Exception:
                logger.error(
                    "Failed to parse active config at %s, using cached/default config",
                    ACTIVE_EDGE_CONFIG_PATH,
                    exc_info=True,
                )
        return cls._cached_config

    @staticmethod
    def detector_configs(config: EdgeEndpointConfig) -> dict[str, InferenceConfig]:
        """Return a mapping of detector IDs to their InferenceConfig."""
        if not config.detectors:
            return {}
        return {d.detector_id: config.edge_inference_configs[d.edge_inference_config] for d in config.detectors}

    @staticmethod
    def detector_config(config: EdgeEndpointConfig, detector_id: str) -> InferenceConfig | None:
        """Return the InferenceConfig for a single detector, or None."""
        for d in config.detectors:
            if d.detector_id == detector_id:
                return config.edge_inference_configs[d.edge_inference_config]
        return None


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
    desired = {d.detector_id for d in new_config.detectors}
    return current_detector_ids - desired, desired - current_detector_ids


def reconcile_config(new_config: EdgeEndpointConfig, db_manager: DatabaseManager) -> None:
    """Diff desired config against DB, mark detectors for deletion/creation, then save config to disk."""
    current = get_active_detector_ids(db_manager)
    removed, added = compute_detector_diff(current, new_config)

    apply_detector_changes(removed, added, db_manager)
    EdgeConfigManager.save(new_config)
    logger.info(
        f"Config reconciled: {len(removed)} detector(s) removed, {len(added)} detector(s) added. "
        f"Removed detectors: {removed} | Added detectors: {added}"
    )
