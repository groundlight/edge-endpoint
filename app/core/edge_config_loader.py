import logging
import os
from typing import Dict

import yaml

from .configs import EdgeInferenceConfig, RootEdgeConfig
from .file_paths import DEFAULT_EDGE_CONFIG_PATH, RUNTIME_EDGE_CONFIG_PATHS

logger = logging.getLogger(__name__)


def _find_runtime_config_path() -> str | None:
    """Return the first runtime config path that exists on this container, or None."""
    for path in RUNTIME_EDGE_CONFIG_PATHS:
        if os.path.exists(path):
            return path
    return None


def load_edge_config() -> RootEdgeConfig:
    """
    Load the edge config, checking sources in priority order:
    1. EDGE_CONFIG environment variable (inline YAML)
    2. Runtime config file on shared PVC (written by POST /edge/configure)
    3. Default config file (ConfigMap mount)
    """
    yaml_config = os.environ.get("EDGE_CONFIG", "").strip()
    if yaml_config:
        return _load_config_from_yaml(yaml_config)

    runtime_path = _find_runtime_config_path()
    if runtime_path:
        logger.info(f"Loading edge config from runtime file: {runtime_path}")
        with open(runtime_path, "r") as f:
            return _load_config_from_yaml(f)

    if os.path.exists(DEFAULT_EDGE_CONFIG_PATH):
        logger.info(f"Loading edge config from {DEFAULT_EDGE_CONFIG_PATH}")
        with open(DEFAULT_EDGE_CONFIG_PATH, "r") as f:
            return _load_config_from_yaml(f)

    raise FileNotFoundError(f"Could not find edge config file in default location: {DEFAULT_EDGE_CONFIG_PATH}")


def save_runtime_edge_config(config: RootEdgeConfig) -> None:
    """Write the config to the first writable runtime config path on the shared PVC."""
    for path in RUNTIME_EDGE_CONFIG_PATHS:
        parent = os.path.dirname(path)
        if os.path.isdir(parent):
            data = config.model_dump()
            # Convert detectors dict back to list format for YAML compatibility
            data["detectors"] = list(data["detectors"].values())
            with open(path, "w") as f:
                yaml.safe_dump(data, f, sort_keys=False)
            logger.info(f"Saved runtime edge config to {path}")
            return
    logger.warning(f"Could not find a writable runtime config path. Tried: {RUNTIME_EDGE_CONFIG_PATHS}")


def _load_config_from_yaml(yaml_config) -> RootEdgeConfig:
    """
    Creates a `RootEdgeConfig` from the config yaml. Raises an error if there are duplicate detector ids.
    """
    config = yaml.safe_load(yaml_config)

    detectors = config.get("detectors", [])
    detector_ids = [det["detector_id"] for det in detectors]

    # Check for duplicate detector IDs
    if len(detector_ids) != len(set(detector_ids)):
        raise ValueError("Duplicate detector IDs found in the configuration. Each detector should only have one entry.")

    config["detectors"] = {det["detector_id"]: det for det in detectors}

    return RootEdgeConfig(**config)


def get_detector_inference_configs(
    root_edge_config: RootEdgeConfig,
) -> dict[str, EdgeInferenceConfig] | None:
    """
    Produces a dict mapping detector IDs to their associated `EdgeInferenceConfig`.
    Returns None if there are no detectors in the config file.
    """
    # Mapping of config names to EdgeInferenceConfig objects
    edge_inference_configs: dict[str, EdgeInferenceConfig] = root_edge_config.edge_inference_configs

    # Filter out detectors whose ID's are empty strings
    detectors = {det_id: detector for det_id, detector in root_edge_config.detectors.items() if det_id != ""}

    detector_to_inference_config: dict[str, EdgeInferenceConfig] | None = None
    if detectors:
        detector_to_inference_config = {
            detector_id: edge_inference_configs[detector_config.edge_inference_config]
            for detector_id, detector_config in detectors.items()
        }

    return detector_to_inference_config


def get_detector_edge_configs_by_id() -> Dict[str, EdgeInferenceConfig]:
    """
    Convenience helper that loads the edge config and returns detector-level inference configs,
    defaulting to an empty dict when none are defined.
    """
    root_config = load_edge_config()
    detector_configs = get_detector_inference_configs(root_config)
    return detector_configs or {}
