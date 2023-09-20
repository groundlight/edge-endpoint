import logging
import os
import shutil
import socket
import time
from typing import Dict, Optional

import numpy as np
import requests
import tritonclient.http as tritonclient
from jinja2 import Template

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
        self.inference_client = tritonclient.InferenceServerClient(url=self.INFERENCE_SERVER_URL, verbose=verbose)
        self.inference_config = config

    def inference_is_available(self, detector_id: str, model_version: str = "") -> bool:
        """
        Queries the inference server to see if everything is ready to perform inference.
        Args:
            detector_id: ID of the detector on which to run local edge inference
        Returns:
            True if edge inference for the specified detector is available, False otherwise
        """
        if detector_id not in self.inference_config.keys():
            logger.debug(f"Edge inference is not enabled for {detector_id=}")
            return False

        try:
            if not self.inference_client.is_server_live():
                logger.debug("Edge inference server is not live")
                return False
            if not self.inference_client.is_model_ready(detector_id, model_version=model_version):
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
        img_numpy = img_numpy.transpose(2, 0, 1)  # [H, W, C=3] -> [C=3, H, W]
        imginput = tritonclient.InferInput(self.INPUT_IMAGE_NAME, img_numpy.shape, datatype="UINT8")
        imginput.set_data_from_numpy(img_numpy)
        outputs = [tritonclient.InferRequestedOutput(f) for f in self.MODEL_OUTPUTS]

        logger.debug("Submitting image to edge inference service")
        start = time.monotonic()
        response = self.inference_client.infer(
            model_name=detector_id,
            inputs=[imginput],
            outputs=outputs,
            request_id="",
        )
        end = time.monotonic()

        output_dict = {k: response.as_numpy(k)[0] for k in self.MODEL_OUTPUTS}
        output_dict["label"] = "NO" if output_dict["label"] else "YES"  # map false / 0 to "YES" and true / 1 to "NO"

        logger.debug(
            f"Inference server response for model={detector_id}: {output_dict}.\n"
            f"Inference time: {end - start:.3f} seconds"
        )
        return output_dict

    def update_model(self, detector_id: str) -> None:
        """
        Request a new model from the cloud and update the local edge inference server.
        """
        logger.info(f"Attemping to update model for {detector_id}")

        model_urls = fetch_model_urls(detector_id)
        pipeline_config = model_urls["pipeline_config"]
        model_buffer = get_object_using_presigned_url(model_urls["model_binary_url"])

        old_version, new_version = save_model_to_repository(detector_id, model_buffer, pipeline_config)

        try:
            self.inference_client.load_model(model_name=detector_id)  # refreshes the model if already loaded
        except (ConnectionRefusedError, socket.gaierror) as ex:
            logger.warning(f"Edge inference server is not available: {ex}")
            return

        retries = 6
        while not self.inference_is_available(detector_id, model_version=str(new_version)):
            if retries == 0:
                logger.warning(
                    f"Edge inference server is not ready to run model version {new_version} for {detector_id}"
                )
                return
            retries -= 1
            time.sleep(5)  # Wait up to 30 seconds for model to be ready

        logger.info(f"Now running inference with model version {new_version} for {detector_id}")
        if old_version is not None:
            delete_model_version(detector_id, old_version)


def fetch_model_urls(detector_id) -> dict[str, str]:
    GROUNDLIGHT_API_TOKEN = os.getenv("GROUNDLIGHT_API_TOKEN")
    if not GROUNDLIGHT_API_TOKEN:
        raise Exception("GROUNDLIGHT_API_TOKEN environment variable is not set")

    url = f"https://api.groundlight.ai/edge-api/v1/fetch-model-urls/{detector_id}/"
    headers = {
        "x-api-token": GROUNDLIGHT_API_TOKEN,
    }
    response = requests.get(url, headers=headers, timeout=10)

    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Failed to fetch model URLs for {detector_id=}. HTTP Status code: {response.status_code}")


def get_object_using_presigned_url(presigned_url):
    response = requests.get(presigned_url, timeout=10)
    if response.status_code == 200:
        return response.content
    else:
        raise Exception("Failed to retrieve data from {presigned_url}. HTTP Status code: {response.status_code}")


def save_model_to_repository(detector_id, model_buffer, pipeline_config) -> tuple[Optional[int], int]:
    """
    Make new version-directory for the model and save the new version of the model and pipeline config to it.
    Model repository directory structure:
    ```
    <model-repository-path>/
        <model-name>/
            [config.pbtxt]
            [<output-labels-file> ...]
            <version>/
                <model-definition-file (e.g. model.py, model.buf, etc)>
    ```
    See the following resources for more information:
    - https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/user_guide/model_repository.html
    - https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/user_guide/model_repository.html#python-models
    - https://github.com/triton-inference-server/python_backend?tab=readme-ov-file#usage
    """
    model_dir = os.path.join(EdgeInferenceManager.MODEL_REPOSITORY, detector_id)
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

    # Add/Overwrite model configuration files (config.pbtxt and binary_labels.txt)
    create_file_from_template(
        template_values={"model_name": detector_id},
        destination=os.path.join(model_dir, "config.pbtxt"),
        template="app/resources/config_template.pbtxt",
    )
    shutil.copy2(src="app/resources/binary_labels.txt", dst=os.path.join(model_dir, "binary_labels.txt"))

    logger.warning(f"Wrote new model version {new_model_version} for {detector_id}")
    return old_model_version, new_model_version


def get_current_model_version(model_dir: str) -> Optional[int]:
    """Triton inference server model_repositories contain model versions in subdirectories. These subdirectories
    are named with integers. This function returns the highest integer in the model repository directory.
    """
    model_versions = [int(d) for d in os.listdir(model_dir) if os.path.isdir(os.path.join(model_dir, d))]
    return max(model_versions) if model_versions else None


def create_file_from_template(template_values: dict, destination: str, template: str):
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


def delete_model_version(detector_id: str, model_version: int):
    """Recursively delete directory detector_id/model_version"""
    model_dir = os.path.join(EdgeInferenceManager.MODEL_REPOSITORY, detector_id)
    model_version_dir = os.path.join(model_dir, str(model_version))
    logger.info(f"Deleting model version {model_version} for {detector_id}")
    if os.path.exists(model_version_dir):
        shutil.rmtree(model_version_dir)
