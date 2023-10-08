import os
import logging
import time
from app.core.app_state import load_edge_config
from app.core.configs import RootEdgeConfig
from app.core.edge_inference import EdgeInferenceManager

from app.core.kubernetes_management import InferenceDeploymentManager

log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=log_level)


def update_models(edge_inference_manager: EdgeInferenceManager, deployment_manager: InferenceDeploymentManager):
    if not os.environ.get("DEPLOY_DETECTOR_LEVEL_INFERENCE", None) or not edge_inference_manager.inference_config:
        return

    inference_config = edge_inference_manager.inference_config

    if not any([config.enabled for config in inference_config.values()]):
        logging.info(f"Edge inference is not enabled for any detectors.")
        return

    # All detectors should have the same refresh rate.
    refresh_rates = [config.refresh_rate for config in inference_config.values()]
    if len(set(refresh_rates)) != 1:
        logging.error(f"Detectors have different refresh rates.")
    refresh_rate = refresh_rates[0]

    while True:
        for detector_id, config in inference_config.items():
            if config.enabled:
                try:
                    # Download and write new model to model repo on disk
                    new_model = edge_inference_manager.update_model(detector_id=detector_id)

                    deployment = deployment_manager.get_inference_deployment(detector_id=detector_id)
                    if deployment is None:
                        deployment_manager.create_inference_deployment(detector_id=detector_id)
                    elif new_model:
                        # Update inference deployment and rollout a new pod
                        deployment_manager.update_inference_deployment(detector_id=detector_id)

                    # TODO: poll for readiness before proceeding to avoid running too many k8s commands
                    # TODO: delete old model versions from disk to save space
                except Exception:
                    logging.error(f"Failed to update model for {detector_id}", exc_info=True)

        time.sleep(refresh_rate)


if __name__ == "__main__":
    edge_config: RootEdgeConfig = load_edge_config()
    edge_inference_templates = edge_config.local_inference_templates
    inference_config = {
        detector.detector_id: edge_inference_templates[detector.local_inference_template]
        for detector in edge_config.detectors
    }

    edge_inference_manager = EdgeInferenceManager(config=inference_config, verbose=True)
    deployment_manager = InferenceDeploymentManager()

    update_models(edge_inference_manager=edge_inference_manager, deployment_manager=deployment_manager)
