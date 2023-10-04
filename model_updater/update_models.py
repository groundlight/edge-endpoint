import os
import logging
import time
from app.core.utils import load_edge_config
from app.core.configs import RootEdgeConfig
from app.core.edge_inference import EdgeInferenceManager

log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=log_level)


def update_models(edge_inference_manager: EdgeInferenceManager):
    if not os.environ.get("DEPLOY_DETECTOR_LEVEL_INFERENCE", None):
        return

    inference_config = edge_inference_manager.inference_config
    refresh_rate = inference_config.refresh_rate

    while True:
        for detector_id, inference_config in inference_config.items():
            if inference_config.enabled:
                try:
                    edge_inference_manager.update_model(detector_id=detector_id)
                except Exception as e:
                    logging.error(f"Failed to update model for {detector_id}. {e}", exc_info=True)

        time.sleep(refresh_rate)


if __name__ == "__main__":
    edge_config: RootEdgeConfig = load_edge_config()
    edge_inference_templates = edge_config.local_inference_templates
    inference_config = {
        detector.detector_id: edge_inference_templates[detector.local_inference_template]
        for detector in edge_config.detectors
    }
    edge_inference_manager = EdgeInferenceManager(config=inference_config, verbose=True)

    update_models(edge_inference_manager=edge_inference_manager)
