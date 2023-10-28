import asyncio
import logging
import os
import time
from typing import Dict, List

from app.core.app_state import load_edge_config
from app.core.configs import RootEdgeConfig
from app.core.database import DatabaseManager
from app.core.edge_inference import EdgeInferenceManager, delete_old_model_versions
from app.core.kubernetes_management import InferenceDeploymentManager

log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=log_level)

REFRESH_RATE = 60
TEN_MINUTES = 60 * 10
DATABASE_CHECK_INTERVAL = 60


def sleep_forever(message: str | None = None):
    while True:
        logging.info(message)
        time.sleep(TEN_MINUTES)


def get_detector_ids_without_deployments(db_manager: DatabaseManager) -> List[Dict[str, str]] | None:
    """
    NOTE: `asyncio.run` is used here because this function is called from a synchronous context.
    :param db_manager: Database manager instance.
    """
    return asyncio.run(db_manager.query_detector_deployments(deployment_created=False))


def _check_new_models_and_inference_deployments(
    detector_id: str,
    edge_inference_manager: EdgeInferenceManager,
    deployment_manager: InferenceDeploymentManager,
    db_manager: DatabaseManager,
) -> None:
    # Download and write new model to model repo on disk
    new_model = edge_inference_manager.update_model(detector_id=detector_id)

    deployment = deployment_manager.get_inference_deployment(detector_id=detector_id)
    if deployment is None:
        logging.info(f"Creating a new inference deployment for {detector_id}")
        deployment_manager.create_inference_deployment(detector_id=detector_id)
        return

    if new_model:
        # Update inference deployment and rollout a new pod
        logging.info(f"Updating inference deployment for {detector_id}")
        deployment_manager.update_inference_deployment(detector_id=detector_id)

        poll_start = time.time()
        while not deployment_manager.is_inference_deployment_rollout_complete(detector_id):
            time.sleep(5)
            if time.time() - poll_start > TEN_MINUTES:
                raise TimeoutError("Inference deployment is not ready within time limit")

        # Now that we have successfully rolled out a new model version, we can clean up our model repository a bit.
        # To be a bit conservative, we keep the current model version as well as the version before that. Older
        # versions of the model for the current detector_id will be removed from disk.
        logging.info(f"Cleaning up old model versions for {detector_id}")
        delete_old_model_versions(detector_id, repository_root=edge_inference_manager.MODEL_REPOSITORY, num_to_keep=2)

    # Database transaction to update the deployment_created field for the detector_id
    # At this time, we are sure that the deployment for the detector has been successfully created and rolled out.
    asyncio.run(db_manager.update_detector_deployment_record(detector_id=detector_id))


def update_models(
    edge_inference_manager: EdgeInferenceManager,
    deployment_manager: InferenceDeploymentManager,
    db_manager: DatabaseManager,
) -> None:
    if not os.environ.get("DEPLOY_DETECTOR_LEVEL_INFERENCE", None):
        sleep_forever("Edge inference is disabled globally... sleeping forever.")
        return

    while True:
        start = time.time()
        for detector_id in edge_inference_manager.inference_config.keys():
            try:
                _check_new_models_and_inference_deployments(
                    detector_id=detector_id,
                    edge_inference_manager=edge_inference_manager,
                    deployment_manager=deployment_manager,
                    db_manager=db_manager,
                )
            except Exception:
                logging.error(f"Failed to update model for {detector_id}", exc_info=True)

        elapsed_s = time.time() - start
        if elapsed_s < REFRESH_RATE:
            time.sleep(REFRESH_RATE - elapsed_s)

        # Fetch detector IDs that need to be deployed from the database and add them to the config
        undeployed_detector_ids: List[Dict[str, str]] = get_detector_ids_without_deployments(db_manager=db_manager)
        if undeployed_detector_ids:
            for detector_record in undeployed_detector_ids:
                detector_id, api_token = detector_record["detector_id"], detector_record["api_token"]
                edge_inference_manager.update_inference_config(detector_id=detector_id, api_token=api_token)


if __name__ == "__main__":
    edge_config: RootEdgeConfig = load_edge_config()
    edge_inference_templates = edge_config.local_inference_templates
    detectors = list(filter(lambda detector: detector.detector_id != "", edge_config.detectors))

    inference_config = None
    if detectors:
        inference_config = {
            detector.detector_id: edge_inference_templates[detector.local_inference_template] for detector in detectors
        }

    edge_inference_manager = EdgeInferenceManager(config=inference_config, verbose=True)
    deployment_manager = InferenceDeploymentManager()

    # We will delegate creation of database tables to the edge-endpoint container.
    # So here we don't run a task to create the tables if they don't already exist.
    db_manager = DatabaseManager()

    update_models(
        edge_inference_manager=edge_inference_manager, deployment_manager=deployment_manager, db_manager=db_manager
    )
