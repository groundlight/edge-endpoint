import logging
import os
from typing import Dict

from groundlight.edge import EdgeEndpointConfig, InferenceConfig

from .file_paths import DEFAULT_EDGE_CONFIG_PATH

logger = logging.getLogger(__name__)


def load_edge_config() -> EdgeEndpointConfig:
    """
    Reads the edge config from the EDGE_CONFIG environment variable if it exists.
    If EDGE_CONFIG is not set, reads the default edge config file.
    """
    yaml_config = os.environ.get("EDGE_CONFIG", "").strip()
    if yaml_config:
        return EdgeEndpointConfig.from_yaml(yaml_config)

    logger.warning("EDGE_CONFIG environment variable not set. Checking default locations.")

    if os.path.exists(DEFAULT_EDGE_CONFIG_PATH):
        logger.info(f"Loading edge config from {DEFAULT_EDGE_CONFIG_PATH}")
        with open(DEFAULT_EDGE_CONFIG_PATH, "r") as f:
            return EdgeEndpointConfig.from_yaml(f)

    raise FileNotFoundError(f"Could not find edge config file in default location: {DEFAULT_EDGE_CONFIG_PATH}")


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
