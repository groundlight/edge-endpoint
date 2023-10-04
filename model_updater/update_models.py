import os
import logging
import time
from app.core.utils import load_edge_config
from app.core.configs import RootEdgeConfig
from app.core.edge_inference import EdgeInferenceManager

log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=log_level)


def update_models():
    if not os.environ.get("DEPLOY_DETECTOR_LEVEL_INFERENCE", None):
        return

    edge_config: RootEdgeConfig = load_edge_config()

    edge_inference_templates = edge_config.local_inference_templates
    inference_config = {
        detector.detector_id: edge_inference_templates[detector.local_inference_template]
        for detector in edge_config.detectors
    }

    edge_inference_manager = EdgeInferenceManager(config=edge_config.local_inference_templates, verbose=True)

    for detector_id, inference_config in inference_config.items():
        if inference_config.enabled:
            try:
                edge_inference_manager.update_model(detector_id=detector_id)
            except Exception as e:
                logging.error(f"Failed to update model for {detector_id}. {e}", exc_info=True)


if __name__ == "__main__":
    while True:
        update_models()
        time.sleep(3600)
