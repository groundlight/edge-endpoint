import logging
import os
import time

from app.core.app_state import get_detector_inference_configs, load_edge_config
from app.core.configs import RootEdgeConfig
from app.core.database import DatabaseManager
from app.core.edge_inference import (
    EdgeInferenceManager,
    delete_old_model_versions,
    get_edge_inference_deployment_name,
    get_edge_inference_model_name,
)
from app.core.kubernetes_management import InferenceDeploymentManager

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL, format="%(asctime)s.%(msecs)03d %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

TEN_MINUTES = 60 * 10

USE_MINIMAL_IMAGE = os.environ.get("USE_MINIMAL_IMAGE", "false") == "true"


def sleep_forever(message: str | None = None):
    while True:
        logger.info(message)
        time.sleep(TEN_MINUTES)


def _check_new_models_and_inference_deployments(
    detector_id: str,
    edge_inference_manager: EdgeInferenceManager,
    deployment_manager: InferenceDeploymentManager,
    db_manager: DatabaseManager,
    separate_oodd_inference: bool,
) -> None:
    """
    Check if there are new models available for the detector_id. If so, update the inference deployment
    to reflect the new state. This is also the entrypoint for creating a new inference deployment
    and updating the database record for the detector_id (i.e., setting deployment_created to True
    when we have successfully rolled out the inference deployment).

    :param detector_id: the detector_id for which we are checking for new models and inference deployments.
    :param edge_inference_manager: the edge inference manager object.
    :param deployment_manager: the inference deployment manager object.
    :param db_manager: the database manager object.
    :param separate_oodd_inference: whether or not to run inference separately for an OODD model
    """
    # Download and write new model to model repo on disk
    new_model = edge_inference_manager.update_models_if_available(detector_id=detector_id)

    edge_deployment_name = get_edge_inference_deployment_name(detector_id)
    edge_deployment = deployment_manager.get_inference_deployment(deployment_name=edge_deployment_name)
    deployment_created = False
    if edge_deployment is None:
        logger.info(f"Creating a new edge inference deployment for {detector_id}")
        deployment_manager.create_inference_deployment(detector_id=detector_id)
        deployment_created = True

    if separate_oodd_inference:
        oodd_deployment_name = get_edge_inference_deployment_name(detector_id, is_oodd=True)
        oodd_deployment = deployment_manager.get_inference_deployment(deployment_name=oodd_deployment_name)
        if oodd_deployment is None:
            logger.info(f"Creating a new oodd inference deployment for {detector_id}")
            deployment_manager.create_inference_deployment(detector_id=detector_id, is_oodd=True)
            deployment_created = True

    # Keep the liveness probe robust across host suspend/resume for GPU deployments.
    # This is safe to run repeatedly; it only patches when needed.
    try:
        deployment_manager.ensure_cuda_liveness_probe(detector_id=detector_id, is_oodd=False)
        if separate_oodd_inference:
            deployment_manager.ensure_cuda_liveness_probe(detector_id=detector_id, is_oodd=True)
    except Exception as e:
        logger.info(
            f"Failed to ensure CUDA liveness probe for {detector_id=}. Error: {e}",
            exc_info=True,
        )

    # Only need to update the deployment if there is a new model and the deployment wasn't just created.
    # Attempting to update a recently created deployment can result in a Kubernetes 409 exception, so it's best to avoid this.
    # During start up this step will be skipped because deployment_created = True, which has the nice effect that inference pods will all
    # come online right away, thus saving time. Subsequent model updates will become single-threaded in order to manage memory/CPU more wisely.
    if new_model and not deployment_created:
        # Update inference deployment and rollout a new pod
        logger.info(f"Updating inference deployment for {detector_id}")
        deployment_manager.update_inference_deployment(detector_id=detector_id)
        if separate_oodd_inference:
            deployment_manager.update_inference_deployment(detector_id=detector_id, is_oodd=True)

        # Poll until the deployment rollout begins
        # There is a slight delay between `update_inference_deployment` and Kubernetes actually starting the rollout, so it's important to wait for this
        logger.info(f"Waiting for inference deployments ({edge_deployment_name} and {oodd_deployment_name}) to start")
        rollout_start_timeout = 10
        poll_start = time.time()
        while deployment_manager.is_inference_deployment_rollout_complete(deployment_name=edge_deployment_name) or (
            separate_oodd_inference
            and deployment_manager.is_inference_deployment_rollout_complete(deployment_name=oodd_deployment_name)
        ):
            time.sleep(0.5)
            if time.time() - poll_start > rollout_start_timeout:
                raise TimeoutError(
                    f"Inference deployments ({edge_deployment_name} and {oodd_deployment_name}) did not start within time limit"
                )

        # Poll until the rollout completes
        logger.info(
            f"Waiting for inference deployments ({edge_deployment_name} and {oodd_deployment_name}) to complete"
        )
        poll_start = time.time()
        while not deployment_manager.is_inference_deployment_rollout_complete(deployment_name=edge_deployment_name) or (
            separate_oodd_inference
            and not deployment_manager.is_inference_deployment_rollout_complete(deployment_name=oodd_deployment_name)
        ):
            time.sleep(5)
            if time.time() - poll_start > TEN_MINUTES:
                raise TimeoutError(
                    f"Inference deployments ({edge_deployment_name} and {oodd_deployment_name}) are not ready within time limit"
                )

        # Now that we have successfully rolled out new model versions, we can clean up our model repository a bit.
        # To be a bit conservative, we keep the current model version as well as the version before that. Older
        # versions of the model for the current detector_id will be removed from disk.
        logger.info(f"Cleaning up old model versions for {detector_id}")
        delete_old_model_versions(detector_id, repository_root=edge_inference_manager.MODEL_REPOSITORY, num_to_keep=2)

    if deployment_manager.is_inference_deployment_rollout_complete(deployment_name=edge_deployment_name) and (
        not separate_oodd_inference
        or deployment_manager.is_inference_deployment_rollout_complete(deployment_name=oodd_deployment_name)
    ):
        # Database transaction to update the deployment_created field for the detector_id
        # At this time, we are sure that the deployment for the detector has been successfully created and rolled out.

        primary_model_name = get_edge_inference_model_name(detector_id)
        db_manager.update_inference_deployment_record(
            model_name=primary_model_name,
            fields_to_update={"deployment_created": True, "deployment_name": edge_deployment_name},
        )
        if separate_oodd_inference:
            oodd_model_name = get_edge_inference_model_name(detector_id, is_oodd=True)
            db_manager.update_inference_deployment_record(
                model_name=oodd_model_name,
                fields_to_update={"deployment_created": True, "deployment_name": oodd_deployment_name},
            )


def manage_update_models(
    edge_inference_manager: EdgeInferenceManager,
    deployment_manager: InferenceDeploymentManager,
    db_manager: DatabaseManager,
    refresh_rate: float,
    separate_oodd_inference: bool,
) -> None:
    """
    Periodically update inference models for detectors.

    -  For existing inference deployments, if a new model is available (i.e., it was fetched
      successfully from the edge-api/v1/fetch-model-urls endpoint), then we will rollout a new
      pod with the new model. If a new model is not available, then we will do nothing.

    - We will also look for new detectors that need to be deployed. These are expected to be
      found in the database. Found detectors will be added to the queue of detectors that need
      an inference deployment.

    NOTE: The periodicity of this task is controlled by the refresh_rate parameter.
    It is settable in the edge config file (defaults to 2 minutes).

    :param edge_inference_manager: the edge inference manager object.
    :param deployment_manager: the inference deployment manager object.
    :param db_manager: the database manager object.
    :param refresh_rate: the time interval (in seconds) between model update calls.
    :param separate_oodd_inference: whether to run inference separately for an OODD model.
    """
    deploy_detector_level_inference = bool(int(os.environ.get("DEPLOY_DETECTOR_LEVEL_INFERENCE", 0)))
    if not deploy_detector_level_inference:
        sleep_forever("Edge inference is disabled globally... sleeping forever.")
        return

    while True:
        start = time.time()
        logger.debug("Starting model update check for existing inference deployments.")
        for detector_id in edge_inference_manager.detector_inference_configs.keys():
            try:
                logger.debug(f"Checking new models and inference deployments for detector_id: {detector_id}")
                _check_new_models_and_inference_deployments(
                    detector_id=detector_id,
                    edge_inference_manager=edge_inference_manager,
                    deployment_manager=deployment_manager,
                    db_manager=db_manager,
                    separate_oodd_inference=separate_oodd_inference,
                )
                logger.debug(f"Successfully updated model for detector_id: {detector_id}")
            except Exception as e:
                logger.info(f"Failed to update model for detector_id: {detector_id}. Error: {e}", exc_info=True)

        elapsed_s = time.time() - start
        logger.debug(f"Model update check completed in {elapsed_s:.2f} seconds.")
        if elapsed_s < refresh_rate:
            sleep_duration = refresh_rate - elapsed_s
            logger.debug(f"Sleeping for {sleep_duration:.2f} seconds before next update cycle.")
            time.sleep(sleep_duration)

        # Fetch detector IDs that need to be deployed from the database and add them to the config
        logger.debug("Fetching undeployed detector IDs from the database.")
        undeployed_inference_deployments = db_manager.get_inference_deployment_records(deployment_created=False)
        if undeployed_inference_deployments:
            unique_detectors = {record.detector_id: record.api_token for record in undeployed_inference_deployments}
            logger.info(
                f"Found {len(undeployed_inference_deployments)} undeployed inference deployment(s) for {len(unique_detectors)} detector(s). Updating inference config."
            )
            for detector_id, api_token in unique_detectors.items():
                logger.debug(f"Updating inference config for detector_id: {detector_id}")
                edge_inference_manager.update_inference_config(
                    detector_id=detector_id,
                    api_token=api_token,
                )
        else:
            logger.debug("No undeployed inference deployments found.")

        # Update the status of the inference deployments in the database
        deployment_records = db_manager.get_inference_deployment_records()
        # using a set to only get unique detector_ids
        deployed_detector_ids = set(record.detector_id for record in deployment_records)
        for detector_id in deployed_detector_ids:
            primary_deployment_name = get_edge_inference_deployment_name(detector_id)
            primary_deployment_created = (
                deployment_manager.get_inference_deployment(primary_deployment_name) is not None
            )
            db_manager.update_inference_deployment_record(
                model_name=get_edge_inference_model_name(detector_id, is_oodd=False),
                fields_to_update={"deployment_created": primary_deployment_created},
            )

            if separate_oodd_inference:
                oodd_deployment_name = get_edge_inference_deployment_name(detector_id, is_oodd=True)
                oodd_deployment_created = deployment_manager.get_inference_deployment(oodd_deployment_name) is not None
                db_manager.update_inference_deployment_record(
                    model_name=get_edge_inference_model_name(detector_id, is_oodd=True),
                    fields_to_update={"deployment_created": oodd_deployment_created},
                )


if __name__ == "__main__":
    logger.info("Starting model updater.")

    edge_config: RootEdgeConfig = load_edge_config()
    logger.info(f"{edge_config=}")

    refresh_rate = edge_config.global_config.refresh_rate
    detector_inference_configs = get_detector_inference_configs(root_edge_config=edge_config)

    logger.info("Creating edge inference manager, deployment manager, and database manager.")
    edge_inference_manager = EdgeInferenceManager(detector_inference_configs=detector_inference_configs, verbose=True)
    deployment_manager = InferenceDeploymentManager()

    # We will delegate creation of database tables to the edge-endpoint container.
    # So here we don't run a task to create the tables if they don't already exist.
    db_manager = DatabaseManager()

    manage_update_models(
        edge_inference_manager=edge_inference_manager,
        deployment_manager=deployment_manager,
        db_manager=db_manager,
        refresh_rate=refresh_rate,
        separate_oodd_inference=not USE_MINIMAL_IMAGE,
    )
