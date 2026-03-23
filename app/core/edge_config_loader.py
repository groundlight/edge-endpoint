import logging
import os
from typing import Dict

from groundlight.edge import EdgeEndpointConfig, InferenceConfig

from .file_paths import ACTIVE_EDGE_CONFIG_PATH, DEFAULT_EDGE_CONFIG_PATH, HELM_CONFIG_SNAPSHOT_PATH

logger = logging.getLogger(__name__)


def _load_helm_provided_config() -> EdgeEndpointConfig:
    """Load the config provided via helm (env var or mounted ConfigMap file)."""
    yaml_config = os.environ.get("EDGE_CONFIG", "").strip()
    if yaml_config:
        return EdgeEndpointConfig.from_yaml(yaml_str=yaml_config)
    return EdgeEndpointConfig.from_yaml(filename=DEFAULT_EDGE_CONFIG_PATH)


def load_edge_config() -> EdgeEndpointConfig:
    """Load edge config. Helm-provided config wins if it changed since the last set_edge_config.

    On startup, compares the current helm config against a snapshot saved when
    set_edge_config was last called. If they differ, the helm config was updated
    (e.g., helm upgrade) and the PVC runtime override is stale -- delete it.
    If they match, the PVC override is still valid and takes priority.
    """
    helm_config = _load_helm_provided_config()

    if not os.path.exists(ACTIVE_EDGE_CONFIG_PATH):
        return helm_config

    if not os.path.exists(HELM_CONFIG_SNAPSHOT_PATH):
        # PVC file exists but no snapshot -- we can't tell if helm changed.
        # Assume helm wins (fresh deployment over leftover PVC data).
        logger.info("No helm config snapshot found. Deleting PVC runtime config.")
        os.remove(ACTIVE_EDGE_CONFIG_PATH)
        return helm_config

    saved_helm = EdgeEndpointConfig.from_yaml(filename=HELM_CONFIG_SNAPSHOT_PATH)
    if saved_helm.to_payload() != helm_config.to_payload():
        logger.info("Helm-provided config changed since last set_edge_config. Using new helm config.")
        os.remove(ACTIVE_EDGE_CONFIG_PATH)
        os.remove(HELM_CONFIG_SNAPSHOT_PATH)
        return helm_config

    # Helm config unchanged -- the PVC override is valid.
    logger.info(f"Loading runtime edge config from {ACTIVE_EDGE_CONFIG_PATH}")
    return EdgeEndpointConfig.from_yaml(filename=ACTIVE_EDGE_CONFIG_PATH)


def get_detector_inference_configs(
    root_edge_config: EdgeEndpointConfig,
) -> dict[str, InferenceConfig] | None:
    """
    Produces a dict mapping detector IDs to their associated `InferenceConfig`.
    Returns None if there are no detectors in the config file.
    """
    # Mapping of config names to InferenceConfig objects
    edge_inference_configs: dict[str, InferenceConfig] = root_edge_config.edge_inference_configs

    # Filter out detectors whose IDs are empty strings.
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
