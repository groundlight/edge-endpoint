import logging
import os
import shutil
import socket
import time
from typing import Dict, Optional

import numpy as np
import requests
import tritonclient.http as tritonclient
from fastapi import HTTPException
from jinja2 import Template

from app.core.utils import prefixed_ksuid

from .configs import LocalInferenceConfig

logger = logging.getLogger(__name__)


class EdgeInferenceManager:
    INPUT_IMAGE_NAME = "image"
    MODEL_OUTPUTS = ["score", "confidence", "probability", "label"]
    INFERENCE_SERVER_URL = "inference-service:8000"
    MODEL_REPOSITORY = "/mnt/models"

    def __init__(self, config: Dict[str, LocalInferenceConfig], verbose: bool = False) -> None:
        """
        Initializes the edge inference manager.
        Args:
            config: Dictionary of detector IDs to LocalInferenceConfig objects
            verbose: Whether to print verbose logs from the inference server client

        NOTE: 1) The detector IDs should match the detector IDs in the motion detection config.
              2) the `LocalInferenceConfig` object determines if local inference is enabled for
                a specific detector and the model name and version to use for inference.
        """
        self.inference_config = config

        if self.inference_config:
            self.inference_clients = {
                detector_id: tritonclient.InferenceServerClient(
                    url=get_edge_inference_service_name(detector_id) + ":8000", verbose=verbose
                )
                for detector_id in self.inference_config.keys()
                if self.detector_configured_for_local_inference(detector_id)
            }

    @staticmethod
    def _inference_server_url(detector_id: str) -> str:
        inference_service_name = f"inference-service-{detector_id.replace('_', '-').lower()}"
        return f"{inference_service_name}:8000"

    def detector_configured_for_local_inference(self, detector_id: str) -> bool:
        """
        Checks if the detector is configured to run local inference.
        Args:
            detector_id: ID of the detector on which to run local edge inference
        Returns:
            True if the detector is configured to run local inference, False otherwise
        """
        return detector_id in self.inference_config.keys() and self.inference_config[detector_id].enabled

    def inference_is_available(self, detector_id: str, model_version: str = "") -> bool:
        """
        Queries the inference server to see if everything is ready to perform inference.
        Args:
            detector_id: ID of the detector on which to run local edge inference
        Returns:
            True if edge inference for the specified detector is available, False otherwise
        """

        try:
            inference_client = self.inference_clients[detector_id]
        except KeyError:
            logger.debug(f"Failed to look up inference client for {detector_id}")
            return False

        try:
            if not inference_client.is_server_live():
                logger.debug("Edge inference server is not live")
                return False
            if not inference_client.is_model_ready(detector_id, model_version=model_version):
                logger.debug(f"Edge inference model is not ready: {detector_id}/{model_version}")
                return False
        except (ConnectionRefusedError, socket.gaierror) as ex:
            logger.warning(f"Edge inference server is not available: {ex}")
            return False

        return True

    def run_inference(self, detector_id: str, img_numpy: np.ndarray) -> dict:
        """
        Submit an image to the inference server, route to a specific model, and return the results.
        Args:
            detector_id: ID of the detector on which to run local edge inference
            img_numpy: Image as a numpy array (assumes HWC uint8 RGB image)
        Returns:
            Dictionary of inference results with keys:
                - "score": float
                - "confidence": float
                - "probability": float
                - "label": str
        """
        imginput = tritonclient.InferInput(self.INPUT_IMAGE_NAME, img_numpy.shape, datatype="UINT8")
        imginput.set_data_from_numpy(img_numpy)
        outputs = [tritonclient.InferRequestedOutput(f) for f in self.MODEL_OUTPUTS]

        request_id = prefixed_ksuid(prefix="einf_")
        inference_client = self.inference_clients[detector_id]

        logger.debug(f"Submitting image to edge inference service. {request_id=}")
        start = time.monotonic()
        response = inference_client.infer(
            model_name=detector_id,
            inputs=[imginput],
            outputs=outputs,
            request_id=request_id,
        )
        end = time.monotonic()

        output_dict = {k: response.as_numpy(k)[0] for k in self.MODEL_OUTPUTS}
        output_dict["label"] = "NO" if output_dict["label"] else "YES"  # map false / 0 to "YES" and true / 1 to "NO"

        logger.debug(
            f"Inference server response for model={detector_id}: {output_dict}.\n"
            f"Inference time: {end - start:.3f} seconds"
        )
        return output_dict

    def update_model(self, detector_id: str) -> bool:
        """
        Request a new model from Groundlight. If there is a new model available, download it and
        write it to the model repository as a new version.

        Returns True if a new model was downloaded and saved, False otherwise.
        """
        logger.info(f"Checking if there is a new model available for {detector_id}")
        model_urls = fetch_model_urls(detector_id)

        cloud_binary_ksuid = model_urls.get("model_binary_id", None)
        if cloud_binary_ksuid is None:
            logger.warning(f"No model binary ksuid returned for {detector_id}")

        model_dir = os.path.join(self.MODEL_REPOSITORY, detector_id)
        edge_binary_ksuid = get_current_model_ksuid(model_dir)
        if edge_binary_ksuid and cloud_binary_ksuid is not None and cloud_binary_ksuid <= edge_binary_ksuid:
            logger.info(f"No new model available for {detector_id}")
            return False

        logger.info(f"New model binary available ({cloud_binary_ksuid}), attemping to update model for {detector_id}")

        pipeline_config = model_urls["pipeline_config"]

        model_buffer = get_object_using_presigned_url(model_urls["model_binary_url"])
        save_model_to_repository(
            detector_id,
            model_buffer,
            pipeline_config,
            binary_ksuid=cloud_binary_ksuid,
            repository_root=self.MODEL_REPOSITORY,
        )
        # TODO: Safely delete old versions
        return True


def fetch_model_urls(detector_id: str) -> dict[str, str]:
    try:
        groundlight_api_token = os.environ["GROUNDLIGHT_API_TOKEN"]
    except KeyError as ex:
        logger.error("GROUNDLIGHT_API_TOKEN environment variable is not set", exc_info=True)
        raise ex

    logger.debug(f"Fetching model URLs for {detector_id}")

    url = f"https://api.groundlight.ai/edge-api/v1/fetch-model-urls/{detector_id}/"
    headers = {
        "x-api-token": groundlight_api_token,
    }
    response = requests.get(url, headers=headers, timeout=10)

    logger.debug(f"response = {response}")

    if response.status_code == 200:
        return response.json()
    else:
        logger.warning(f"Failure Response: {response.status_code}")

        raise HTTPException(status_code=response.status_code, detail=f"Failed to fetch model URLs for {detector_id=}.")


def get_object_using_presigned_url(presigned_url: str) -> bytes:
    response = requests.get(presigned_url, timeout=10)
    if response.status_code == 200:
        return response.content
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to retrieve data from {presigned_url}.")


def save_model_to_repository(
    detector_id: str,
    model_buffer: bytes,
    pipeline_config: str,
    binary_ksuid: Optional[str],
    repository_root: str,
) -> tuple[Optional[int], int]:
    """
    Make new version-directory for the model and save the new version of the model and pipeline config to it.
    Model repository directory structure:
    ```
    <model-repository-path>/
        <model-name>/
            [config.pbtxt]
            [<output-labels-file> ...]
            <version>/
                <model-definition-file (e.g. model.py, model.buf, model_id.txt, etc)>
    ```
    See the following resources for more information:
    - https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/user_guide/model_repository.html
    - https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/user_guide/model_repository.html#python-models
    - https://github.com/triton-inference-server/python_backend?tab=readme-ov-file#usage
    """
    model_dir = os.path.join(repository_root, detector_id)
    os.makedirs(model_dir, exist_ok=True)

    old_model_version = get_current_model_version(model_dir)
    new_model_version = 1 if old_model_version is None else old_model_version + 1

    model_version_dir = os.path.join(model_dir, str(new_model_version))
    os.makedirs(model_version_dir, exist_ok=True)

    # Add model-version specific files (model.py and model.buf)
    # NOTE: these files should be static and not change between model versions
    create_file_from_template(
        template_values={"pipeline_config": pipeline_config},
        destination=os.path.join(model_version_dir, "model.py"),
        template="app/resources/model_template.py",
    )
    with open(os.path.join(model_version_dir, "model.buf"), "wb") as f:
        f.write(model_buffer)
    if binary_ksuid:
        with open(os.path.join(model_version_dir, "model_id.txt"), "w") as f:
            f.write(binary_ksuid)

    # Add/Overwrite model configuration files (config.pbtxt and binary_labels.txt)
    create_file_from_template(
        template_values={"model_name": detector_id},
        destination=os.path.join(model_dir, "config.pbtxt"),
        template="app/resources/config_template.pbtxt",
    )
    shutil.copy2(src="app/resources/binary_labels.txt", dst=os.path.join(model_dir, "binary_labels.txt"))

    logger.info(f"Wrote new model version {new_model_version} for {detector_id} with {binary_ksuid=}")
    return old_model_version, new_model_version


def get_current_model_version(model_dir: str) -> Optional[int]:
    """Triton inference server model_repositories contain model versions in subdirectories. These subdirectories
    are named with integers. This function returns the highest integer in the model repository directory.
    """
    logger.debug(f"Checking for current model version in {model_dir}")
    if not os.path.exists(model_dir):
        return None
    model_versions = [int(d) for d in os.listdir(model_dir) if os.path.isdir(os.path.join(model_dir, d))]
    return max(model_versions) if model_versions else None


def get_current_model_ksuid(model_dir: str) -> Optional[str]:
    """Read the model_id.txt file in the current model version directory,
    which contains the KSUID of the model binary.
    """
    v = get_current_model_version(model_dir)
    if v is None:
        logger.info(f"No current model version found in {model_dir}")
        return None
    id_file = os.path.join(model_dir, str(v), "model_id.txt")
    if os.path.exists(id_file):
        with open(id_file, "r") as f:
            return f.read()
    else:
        logger.warning(f"No existing model_id.txt file found in {os.path.join(model_dir, str(v))}")
        return None


def create_file_from_template(template_values: dict, destination: str, template: str) -> None:
    """
    This is a helper function to create a file from a Jinja2 template. In your template file,
    place template values in {{ template_value }} blocks. Then pass in a dictionary mapping template
    keys to values. The template will be filled with the values and written to the destination file.

    See https://jinja.palletsprojects.com/en/3.1.x/templates/ for more information on Jinja2 templates.
    """
    # Step 1: Read the template file
    with open(template, "r") as template_file:
        template_content = template_file.read()

    # Step 2: Substitute placeholders with actual values
    template = Template(template_content)
    filled_content = template.render(**template_values)

    # Step 3: Write the filled content to a new file
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    with open(destination, "w") as output_file:
        output_file.write(filled_content)


def delete_model_version(detector_id: str, model_version: int, repository_root: str) -> None:
    """Recursively delete directory detector_id/model_version"""
    model_version_dir = os.path.join(repository_root, detector_id, str(model_version))
    logger.info(f"Deleting model version {model_version} for {detector_id}")
    if os.path.exists(model_version_dir):
        shutil.rmtree(model_version_dir)


def get_edge_inference_service_name(detector_id: str) -> str:
    """
    Kubernetes service/deployment names have a strict naming convention.
    They have to be alphanumeric, lower cased, and can only contain dashes.
    We just use `inferencemodel-<detector_id>` as the deployment name and
    `inference-service-<detector_id>` as the service name.
    """
    return f"inference-service-{detector_id.replace('_', '-').lower()}"


def get_edge_inference_deployment_name(detector_id: str) -> str:
    return f"inferencemodel-{detector_id.replace('_', '-').lower()}"
