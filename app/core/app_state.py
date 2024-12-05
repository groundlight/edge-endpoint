import logging
import os

import yaml
from fastapi import Request

from .configs import EdgeInferenceConfig, RootEdgeConfig
from .database import DatabaseManager
from .edge_inference import EdgeInferenceManager
from .file_paths import DEFAULT_EDGE_CONFIG_PATH

logger = logging.getLogger(__name__)


def load_edge_config() -> RootEdgeConfig:
    """
    Reads the edge config from the EDGE_CONFIG environment variable if it exists.
    If EDGE_CONFIG is not set, reads the default edge config file.
    """
    yaml_config = os.environ.get("EDGE_CONFIG", "").strip()
    if yaml_config:
        return _load_config_from_yaml(yaml_config)

    logger.warning("EDGE_CONFIG environment variable not set. Checking default locations.")

    if os.path.exists(DEFAULT_EDGE_CONFIG_PATH):
        logger.info(f"Loading edge config from {DEFAULT_EDGE_CONFIG_PATH}")
        with open(DEFAULT_EDGE_CONFIG_PATH, "r") as f:
            return _load_config_from_yaml(f)

    raise FileNotFoundError(f"Could not find edge config file in default location: {DEFAULT_EDGE_CONFIG_PATH}")


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


class AppState:
    def __init__(self):
        self.edge_config = load_edge_config()
        detector_inference_configs = get_detector_inference_configs(root_edge_config=self.edge_config)
        self.edge_inference_manager = EdgeInferenceManager(detector_inference_configs=detector_inference_configs)
        self.db_manager = DatabaseManager()
        self.is_ready = False


def get_app_state(request: Request) -> AppState:
    if not hasattr(request.app.state, "app_state"):
        raise RuntimeError("App state is not initialized.")
    return request.app.state.app_state
