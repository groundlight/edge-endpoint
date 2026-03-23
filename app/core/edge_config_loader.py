import logging
import os
from typing import Dict

from groundlight.edge import EdgeEndpointConfig, InferenceConfig

from .file_paths import HELM_EDGE_CONFIG_PATH

logger = logging.getLogger(__name__)


def load_edge_config() -> EdgeEndpointConfig:
    """Load edge config, falling back to Pydantic defaults.

    Sources checked in order:
    1. EDGE_CONFIG env var (used by Docker tests and non-Helm setups)
    2. Helm-mounted ConfigMap file at HELM_EDGE_CONFIG_PATH
    3. EdgeEndpointConfig() Pydantic defaults
    """
    yaml_config = os.environ.get("EDGE_CONFIG", "").strip()
    if yaml_config:
        return EdgeEndpointConfig.from_yaml(yaml_str=yaml_config)
    if os.path.exists(HELM_EDGE_CONFIG_PATH):
        return EdgeEndpointConfig.from_yaml(filename=HELM_EDGE_CONFIG_PATH)
    return EdgeEndpointConfig()


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
