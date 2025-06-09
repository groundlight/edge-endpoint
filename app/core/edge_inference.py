import asyncio
import logging
import os
import shutil
import time
from typing import Optional

import httpx
import requests
import yaml
from cachetools import TTLCache, cached
from fastapi import HTTPException, status
from jinja2 import Template

from app.core.configs import EdgeInferenceConfig
from app.core.file_paths import MODEL_REPOSITORY_PATH
from app.core.speedmon import SpeedMonitor
from app.core.utils import ModelInfoBase, ModelInfoWithBinary, parse_model_info

logger = logging.getLogger(__name__)

# Simple TTL cache for is_edge_inference_ready checks to avoid having to re-check every time a request is processed.
# This will be process-specific, so each edge-endpoint worker will have its own cache instance.
ttl_cache = TTLCache(maxsize=128, ttl=5)


@cached(ttl_cache)
def is_edge_inference_ready(inference_client_url: str) -> bool:
    model_ready_url = f"http://{inference_client_url}/health/ready"
    try:
        response = requests.get(model_ready_url)
        return response.status_code == status.HTTP_200_OK
    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to connect to {model_ready_url}: {e}")
        return False


def submit_image_for_inference(inference_client_url: str, image_bytes: bytes, content_type: str) -> dict:
    inference_url = f"http://{inference_client_url}/infer"
    headers = {"Content-Type": content_type}
    try:
        logger.debug(f"Submitting image for inference to {inference_url}")
        response = requests.post(inference_url, data=image_bytes, headers=headers)
        if response.status_code != status.HTTP_200_OK:
            logger.error(f"Inference server returned an error: {response.status_code} - {response.text}")
            raise RuntimeError(f"Inference server error: {response.status_code} - {response.text}")
        return response.json()
    except httpx.RequestError as e:
        logger.error(f"Failed to connect to {inference_url}: {e}")
        raise RuntimeError("Failed to submit image for inference") from e


def get_inference_result(primary_response: dict, oodd_response: dict) -> str:
    """
    Get the final inference result from the primary and OODD responses.
    """
    primary_num_classes = get_num_classes(primary_response)

    primary_output_dict = parse_inference_response(primary_response)
    logger.debug(f"Primary inference server response: {primary_output_dict}.")
    oodd_output_dict = parse_inference_response(oodd_response)
    logger.debug(f"OODD inference server response: {oodd_output_dict}.")

    combined_output_dict = adjust_confidence_with_oodd(primary_output_dict, oodd_output_dict, primary_num_classes)
    logger.debug(f"Combined (primary + OODD) inference result: {combined_output_dict}.")

    return combined_output_dict


def get_num_classes(response: dict) -> int:
    """
    Get the number of classes from the inference response dictionary.
    """
    multi_predictions: dict = response.get("multi_predictions", None)
    predictions: dict = response.get("predictions", None)
    if multi_predictions is not None and predictions is not None:
        raise ValueError("Got result with both multi_predictions and predictions.")
    if multi_predictions is not None:
        # multiclass or count case
        return len(multi_predictions["probabilities"][0])
    elif predictions is not None:
        # binary case
        return 2
    else:
        raise ValueError(
            "Can't get number of classes from inference response with neither predictions nor multi_predictions."
        )


def adjust_confidence_with_oodd(primary_output_dict: dict, oodd_output_dict: dict, num_classes: int) -> dict:
    """
    Adjust the confidence of the primary result based on the OODD result.

    NOTE: This is a duplication of the cloud inference result OODD confidence adjustment logic. Changes should not be
    made here that bring this out of sync with the cloud OODD confidence adjustment logic. The cloud implementation for
    binary detectors is found in detector_modes_logic, implemented separately for each detector mode.
    """
    oodd_confidence = oodd_output_dict["confidence"]
    oodd_label = oodd_output_dict["label"]
    primary_confidence = primary_output_dict["confidence"]
    if oodd_confidence is None or primary_confidence is None:
        logger.warning("Either the OODD or primary confidence is None, returning the primary result.")
        return primary_output_dict

    # 1.0 is the FAIL (outlier) class
    outlier_probability = oodd_confidence if oodd_label == 1 else 1 - oodd_confidence

    adjusted_confidence = (outlier_probability * 1 / num_classes) + (1 - outlier_probability) * primary_confidence
    logger.debug(
        f"Adjusted confidence of the primary prediction with the OODD prediction. New confidence is {adjusted_confidence}."
    )

    adjusted_output_dict = primary_output_dict.copy()
    adjusted_output_dict["confidence"] = adjusted_confidence
    # Raw prediction data for troubleshooting purposes
    adjusted_output_dict["raw_primary_confidence"] = primary_output_dict["confidence"]
    adjusted_output_dict["raw_oodd_prediction"] = oodd_output_dict.copy()

    return adjusted_output_dict


def parse_inference_response(response: dict) -> dict:
    if "predictions" not in response:
        logger.error(f"Invalid inference response: {response}")
        raise RuntimeError("Invalid inference response")

    # TODO: Clean up and make response parsing more robust.
    # Ideally we would leverage an autogenerated openapi client to handle this.
    #
    # Example response:
    # {
    #     "multi_predictions": None,  # Multiclass / Counting results
    #     "predictions": {"confidences": [0.54], "labels": [0], "probabilities": [0.45], "scores": [-2.94]},  # Binary results
    #     "secondary_predictions": None,  # Text recognition and Obj detection results
    # }
    multi_predictions: dict = response.get("multi_predictions", None)
    predictions: dict = response.get("predictions", None)
    secondary_predictions: dict = response.get("secondary_predictions", None)

    if multi_predictions is not None and predictions is not None:
        raise ValueError("Got result with both multi_predictions and predictions.")
    if multi_predictions is not None:
        # Count or multiclass case
        probabilities: list[float] = multi_predictions["probabilities"][0]
        confidence: float = max(probabilities)
        max_prob_index = max(range(len(probabilities)), key=lambda i: probabilities[i])
        label: int = max_prob_index
    elif predictions is not None:
        # Binary case
        confidence: float = predictions["confidences"][0]
        label: int = predictions["labels"][0]
    else:
        raise ValueError("Got result with no multi_predictions or predictions.")

    rois: list[dict] | None = None
    text: str | None = None
    # Attempt to extract rois / text
    if secondary_predictions is not None:
        roi_predictions: dict[str, list[list[dict]]] | None = secondary_predictions.get("roi_predictions", None)
        text_predictions: list[str] | None = secondary_predictions.get("text_predictions", None)
        if roi_predictions is not None:
            rois = roi_predictions["rois"][0]
            for i, roi in enumerate(rois):
                geometry = roi["geometry"]
                # TODO add validation to calculate x and y automatically
                x = 0.5 * (geometry["left"] + geometry["right"])
                y = 0.5 * (geometry["top"] + geometry["bottom"])
                rois[i]["geometry"]["x"] = x
                rois[i]["geometry"]["y"] = y
        if text_predictions is not None:
            if len(text_predictions) > 1:
                raise ValueError("Got more than one text prediction. This should not happen.")
            text = text_predictions[0]

    output_dict = {"confidence": confidence, "label": label, "text": text, "rois": rois}

    return output_dict


class EdgeInferenceManager:
    INPUT_IMAGE_NAME = "image"
    MODEL_OUTPUTS = ["score", "confidence", "probability", "label"]
    INFERENCE_SERVER_URL = "inference-service:8000"
    MODEL_REPOSITORY = MODEL_REPOSITORY_PATH

    def __init__(
        self,
        detector_inference_configs: dict[str, EdgeInferenceConfig] | None,
        verbose: bool = False,
    ) -> None:
        """
        Initializes the edge inference manager.
        Args:
            detector_inference_configs: Dictionary of detector IDs to EdgeInferenceConfig objects
            edge_config: RootEdgeConfig object
            verbose: Whether to print verbose logs from the inference server client
        """
        self.verbose = verbose
        self.detector_inference_configs, self.inference_client_urls, self.oodd_inference_client_urls = {}, {}, {}
        self.speedmon = SpeedMonitor()

        if detector_inference_configs:
            self.detector_inference_configs = detector_inference_configs
            self.inference_client_urls = {
                detector_id: get_edge_inference_service_name(detector_id) + ":8000"
                for detector_id in self.detector_inference_configs.keys()
                if self.detector_configured_for_edge_inference(detector_id)
            }
            self.oodd_inference_client_urls = {
                detector_id: get_edge_inference_service_name(detector_id, is_oodd=True) + ":8000"
                for detector_id in self.detector_inference_configs.keys()
                if self.detector_configured_for_edge_inference(detector_id)
            }
        # Last time we escalated to cloud for each detector
        self.last_escalation_times = {detector_id: None for detector_id in self.detector_inference_configs.keys()}
        # Minimum time between escalations for each detector
        self.min_times_between_escalations = {
            detector_id: detector_inference_config.min_time_between_escalations
            for detector_id, detector_inference_config in self.detector_inference_configs.items()
        }

    def update_inference_config(self, detector_id: str, api_token: str) -> None:
        """
        Adds a new detector to the inference config at runtime. This is useful when new
        detectors are added to the database and we want to create an inference deployment for them.
        Args:
            detector_id: ID of the detector on which to run local edge inference
            api_token: API token required to fetch inference models

        """
        if detector_id not in self.detector_inference_configs.keys():
            self.detector_inference_configs[detector_id] = EdgeInferenceConfig(enabled=True, api_token=api_token)
            self.inference_client_urls[detector_id] = get_edge_inference_service_name(detector_id) + ":8000"
            self.oodd_inference_client_urls[detector_id] = (
                get_edge_inference_service_name(detector_id, is_oodd=True) + ":8000"
            )
            logger.info(f"Set up edge inference for {detector_id}")

    def detector_configured_for_edge_inference(self, detector_id: str) -> bool:
        """
        Checks if the detector is configured to run local inference.
        Args:
            detector_id: ID of the detector on which to run local edge inference
        Returns:
            True if the detector is configured to run local inference, False otherwise
        """
        if not self.detector_inference_configs:
            return False

        return (
            detector_id in self.detector_inference_configs.keys()
            and self.detector_inference_configs[detector_id].enabled
        )

    def inference_is_available(self, detector_id: str) -> bool:
        """
        Queries the inference server to see if everything is ready to perform inference.
        Args:
            detector_id: ID of the detector on which to run local edge inference
        Returns:
            True if edge inference for the specified detector is available, False otherwise
        """
        try:
            inference_client_url = self.inference_client_urls[detector_id]
            oodd_inference_client_url = self.oodd_inference_client_urls[detector_id]
        except KeyError:
            logger.info(f"Failed to look up inference clients for {detector_id}")
            return False

        inference_clients_are_ready = is_edge_inference_ready(inference_client_url) and is_edge_inference_ready(
            oodd_inference_client_url
        )
        if not inference_clients_are_ready:
            logger.debug("Edge inference server and/or OODD inference server is not ready")
            return False
        return True

    def run_inference(self, detector_id: str, image_bytes: bytes, content_type: str) -> dict:
        """
        Submit an image to the inference server, route to a specific model, and return the results.
        Args:
            detector_id: ID of the detector on which to run local edge inference
            image_bytes: The serialized image to submit for inference
            content_type: The content type of the image
        Returns:
            Dictionary of inference results with keys:
                - "score": float
                - "confidence": float
                - "probability": float
                - "label": str
        """
        logger.info(f"Submitting image to edge inference service. {detector_id=}")
        start_time = time.perf_counter()

        inference_client_url = self.inference_client_urls[detector_id]
        oodd_inference_client_url = self.oodd_inference_client_urls[detector_id]

        response = submit_image_for_inference(inference_client_url, image_bytes, content_type)
        oodd_response = submit_image_for_inference(oodd_inference_client_url, image_bytes, content_type)

        output_dict = get_inference_result(response, oodd_response)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        self.speedmon.update(detector_id, elapsed_ms)
        fps = self.speedmon.average_fps(detector_id)

        logger.debug(f"Inference server response for request {detector_id=}: {output_dict}.")
        logger.info(f"Recent-average FPS for {detector_id=}: {fps:.2f}")
        return output_dict

    def update_models_if_available(self, detector_id: str) -> bool:
        """
        Request a new model from Groundlight. If there is a new model available, download it and
        write it to the model repository as a new version.

        Returns True if a new model was downloaded and saved, False otherwise.
        """
        logger.info(f"Checking if there are new models available for {detector_id}")

        api_token = (
            self.detector_inference_configs[detector_id].api_token
            if self.detector_configured_for_edge_inference(detector_id)
            else None
        )

        # fallback to env var if we don't have a token in the config
        api_token = api_token or os.environ.get("GROUNDLIGHT_API_TOKEN", None)

        edge_model_info, oodd_model_info = fetch_model_info(detector_id, api_token=api_token)

        edge_version, oodd_version = get_current_model_versions(self.MODEL_REPOSITORY, detector_id)
        primary_edge_model_dir = get_primary_edge_model_dir(self.MODEL_REPOSITORY, detector_id)
        oodd_model_dir = get_oodd_model_dir(self.MODEL_REPOSITORY, detector_id)

        update_primary_model = should_update(edge_model_info, primary_edge_model_dir, edge_version)
        update_oodd_model = should_update(oodd_model_info, oodd_model_dir, oodd_version)

        if not update_primary_model and not update_oodd_model:
            logger.debug(f"No new models available for {detector_id}")
            return False

        logger.info(f"At least one new model is available for {detector_id}, saving models to repository.")
        save_models_to_repository(
            detector_id=detector_id,
            edge_model_buffer=get_model_buffer(edge_model_info) if update_primary_model else None,
            edge_model_info=edge_model_info if update_primary_model else None,
            oodd_model_buffer=get_model_buffer(oodd_model_info) if update_oodd_model else None,
            oodd_model_info=oodd_model_info if update_oodd_model else None,
            repository_root=self.MODEL_REPOSITORY,
        )
        return True

    def escalation_cooldown_complete(self, detector_id: str) -> bool:
        """
        Check if the time since the last escalation is long enough ago that we should escalate again.
        The minimum time between escalations for a detector is set by the `min_time_between_escalations` field in the
        detector's config. If the field is not set, we use a default of 2 seconds.

        Args:
            detector_id: ID of the detector to check
        Returns:
            True if there hasn't been an escalation on this detector in the last `min_time_between_escalations` seconds,
              False otherwise.
        """
        min_time_between_escalations = self.min_times_between_escalations.get(detector_id, 2)
        last_escalation_time = self.last_escalation_times[detector_id]

        if last_escalation_time is None or (time.time() - last_escalation_time) > min_time_between_escalations:
            self.last_escalation_times[detector_id] = time.time()
            return True

        return False


def fetch_model_info(detector_id: str, api_token: Optional[str] = None) -> tuple[ModelInfoBase, ModelInfoBase]:
    if not api_token:
        raise ValueError(f"No API token provided for {detector_id=}")

    logger.debug(f"Fetching model info for {detector_id}")

    url = f"https://api.groundlight.ai/edge-api/v1/fetch-model-urls/{detector_id}/"
    headers = {"x-api-token": api_token}
    response = requests.get(url, headers=headers, timeout=10)
    logger.debug(f'fetch-model-urls response.text = "{response.text}", response.status_code = {response.status_code}')

    if response.status_code == status.HTTP_200_OK:
        return parse_model_info(response.json())

    exception_string = f"Failed to fetch model info for detector '{detector_id}'."
    try:
        response_json = response.json()
        if "detail" in response_json:  # Include additional detail on the error if available
            exception_string = f"{exception_string} Received error: {response_json['detail']}"
    except requests.exceptions.JSONDecodeError:
        exception_string = f"{exception_string} Received error: {response.text}"

    raise HTTPException(status_code=response.status_code, detail=exception_string)


def get_model_buffer(model_info: ModelInfoBase) -> bytes | None:
    if isinstance(model_info, ModelInfoWithBinary):
        logger.info(f"New model binary available ({model_info.model_binary_id}), attemping to update model.")
        model_buffer = get_object_using_presigned_url(model_info.model_binary_url)
    else:
        logger.info("Got a pipeline config but no model binary, attempting to update model.")
        model_buffer = None

    return model_buffer


def get_object_using_presigned_url(presigned_url: str) -> bytes:
    response = requests.get(presigned_url, timeout=10)
    if response.status_code == status.HTTP_200_OK:
        return response.content
    else:
        raise HTTPException(status_code=response.status_code, detail=f"Failed to retrieve data from {presigned_url}.")


def save_models_to_repository(
    detector_id: str,
    edge_model_buffer: Optional[bytes],
    edge_model_info: Optional[ModelInfoBase],
    oodd_model_buffer: Optional[bytes],
    oodd_model_info: Optional[ModelInfoBase],
    repository_root: str,
) -> None:
    """
    Make new version-directory for the model and save the new version of the model and pipeline config to it.
    Old model repository directory structure:
    ```
    <model-repository-path>/
        <model-name>/
            <version>/
                <model-definition-files (e.g. model.buf, pipeline_config.yaml, etc)>
    ```

    New model repository directory structure:
    ```
    <model-repository-path>/
        <detector-id (formerly referred to as model-name)>/
            <primary>/
                <version>/
                    <model-definition-files (e.g. model.buf, pipeline_config.yaml, etc)>
            <oodd>/
                <version>/
                    <model-definition-files (e.g. model.buf, pipeline_config.yaml, etc)>
    ```
    """
    edge_model_dir = get_primary_edge_model_dir(repository_root, detector_id)
    oodd_model_dir = get_oodd_model_dir(repository_root, detector_id)
    os.makedirs(edge_model_dir, exist_ok=True)
    os.makedirs(oodd_model_dir, exist_ok=True)

    old_primary_model_version, old_oodd_model_version = get_current_model_versions(repository_root, detector_id)

    if edge_model_info:
        new_primary_model_version = 1 if old_primary_model_version is None else old_primary_model_version + 1
    else:
        new_primary_model_version = old_primary_model_version

    if oodd_model_info:
        new_oodd_model_version = 1 if old_oodd_model_version is None else old_oodd_model_version + 1
    else:
        new_oodd_model_version = old_oodd_model_version

    if edge_model_info:
        save_model_to_repository(edge_model_buffer, edge_model_info, edge_model_dir, new_primary_model_version)
    if oodd_model_info:
        save_model_to_repository(oodd_model_buffer, oodd_model_info, oodd_model_dir, new_oodd_model_version)


def save_model_to_repository(
    model_buffer: bytes, model_info: ModelInfoBase, model_dir: str, model_version: int
) -> None:
    model_version_dir = os.path.join(model_dir, str(model_version))
    os.makedirs(model_version_dir, exist_ok=True)

    if model_buffer:
        with open(os.path.join(model_version_dir, "model.buf"), "wb") as f:
            f.write(model_buffer)

    with open(os.path.join(model_version_dir, "pipeline_config.yaml"), "w") as f:
        yaml.dump(yaml.safe_load(model_info.pipeline_config), f)
    with open(os.path.join(model_version_dir, "predictor_metadata.json"), "w") as f:
        f.write(model_info.predictor_metadata)

    if isinstance(model_info, ModelInfoWithBinary):
        with open(os.path.join(model_version_dir, "model_id.txt"), "w") as f:
            f.write(model_info.model_binary_id)

    logger.info(
        f"Wrote new model version {model_version} to {model_dir}"
        + (f" with model binary id {model_info.model_binary_id}" if isinstance(model_info, ModelInfoWithBinary) else "")
    )


def should_update(model_info: ModelInfoBase, model_dir: str, version: Optional[int]) -> bool:
    """Determines if the model needs to be updated based on the received and current model info."""
    if version is None:
        logger.info(f"No current model version found in {model_dir}, updating model")
        return True

    if isinstance(model_info, ModelInfoWithBinary):
        edge_binary_ksuid = get_current_model_ksuid(model_dir, version)
        if edge_binary_ksuid and model_info.model_binary_id == edge_binary_ksuid:
            logger.info(
                f"The edge binary in {model_dir} is the same as the cloud binary, so we don't need to update the model."
            )
            return False
    else:
        current_pipeline_config = get_current_pipeline_config(model_dir, version)
        if current_pipeline_config and current_pipeline_config == yaml.safe_load(model_info.pipeline_config):
            logger.info(
                f"The current pipeline_config in {model_dir} is the same as the received pipeline_config and we have no model binary, so we don't need to update the model."
            )
            return False

    logger.info(
        f"The model in {model_dir} needs to be updated, the current edge model is different from the cloud model."
    )
    return True


def get_current_model_versions(repository_root: str, detector_id: str) -> tuple[Optional[int], Optional[int]]:
    """Edge inference server model_repositories contain model versions in subdirectories. These subdirectories
    are named with integers. This function returns the highest integer in the model repository directory.
    """
    logger.debug(f"Checking for current model versions for {detector_id}")
    primary_dir = get_primary_edge_model_dir(repository_root, detector_id)
    oodd_dir = get_oodd_model_dir(repository_root, detector_id)

    # If the primary or oodd directories don't exist, we'll update both models. This will happen when the edge endpoint
    # switches from the old model repository format to the new one.
    primary_version = None
    oodd_version = None

    if os.path.exists(primary_dir):
        primary_versions = get_all_model_versions(primary_dir)
        primary_version = max(primary_versions) if primary_versions else None

    if os.path.exists(oodd_dir):
        oodd_versions = get_all_model_versions(oodd_dir)
        oodd_version = max(oodd_versions) if oodd_versions else None

    return primary_version, oodd_version


def get_all_model_versions(model_dir: str) -> list:
    """Edge inference server model_repositories contain model versions in subdirectories.
    Return all such version numbers.
    """
    if not os.path.exists(model_dir):
        return []
    # explicitly exclude primary and oodd directories so we can search for the latest version in the old or new model
    # repository format
    model_versions = [
        int(d)
        for d in os.listdir(model_dir)
        if os.path.isdir(os.path.join(model_dir, d)) and not d.startswith("primary") and not d.startswith("oodd")
    ]
    return model_versions


def get_current_model_ksuid(model_dir: str, model_version: int) -> Optional[str]:
    """Read the model_id.txt file in the current model version directory,
    which contains the KSUID of the model binary (if available).
    """
    id_file = os.path.join(model_dir, str(model_version), "model_id.txt")
    if os.path.exists(id_file):
        with open(id_file, "r") as f:
            return f.read()
    else:
        logger.debug(f"No existing model_id.txt file found in {os.path.join(model_dir, str(model_version))}")
        return None


def get_current_pipeline_config(model_dir: str, model_version: int) -> dict | None:
    """Read the pipeline_config.yaml file in the current model version directory."""
    config_file = os.path.join(model_dir, str(model_version), "pipeline_config.yaml")
    if os.path.exists(config_file):
        with open(config_file, "r") as f:
            return yaml.safe_load(f)
    else:
        logger.warning(f"No existing pipeline_config.yaml file found in {os.path.join(model_dir, str(model_version))}")
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


def delete_old_model_versions(detector_id: str, repository_root: str, num_to_keep: int = 2) -> None:
    """Recursively delete all but the latest model versions"""
    detector_models_dir = get_detector_models_dir(repository_root, detector_id)
    primary_edge_model_dir = get_primary_edge_model_dir(repository_root, detector_id)
    oodd_model_dir = get_oodd_model_dir(repository_root, detector_id)

    # We will delete all model versions in the old model repository format
    old_dir_model_versions = get_all_model_versions(detector_models_dir)
    if len(old_dir_model_versions) > 0:
        logger.info(f"Deleting all model versions in the old model repository format for {detector_id}")

        for v in old_dir_model_versions:
            delete_model_version(detector_models_dir, v)

    # We will also delete all but the latest num_to_keep model versions in the new model repository format
    primary_model_versions = get_all_model_versions(primary_edge_model_dir)
    oodd_model_versions = get_all_model_versions(oodd_model_dir)
    primary_model_versions = sorted(primary_model_versions)
    oodd_model_versions = sorted(oodd_model_versions)

    primary_versions_to_delete = (
        primary_model_versions[:-num_to_keep] if len(primary_model_versions) > num_to_keep else []
    )
    oodd_versions_to_delete = oodd_model_versions[:-num_to_keep] if len(oodd_model_versions) > num_to_keep else []

    logger.info(f"Deleting {len(primary_versions_to_delete)} old primary edge model version(s) for {detector_id}")
    for v in primary_versions_to_delete:
        delete_model_version(primary_edge_model_dir, v)

    logger.info(f"Deleting {len(oodd_versions_to_delete)} old OODD model version(s) for {detector_id}")
    for v in oodd_versions_to_delete:
        delete_model_version(oodd_model_dir, v)


def delete_model_version(model_dir: str, model_version: int) -> None:
    """Recursively delete directory model_dir/model_version"""
    model_version_dir = os.path.join(model_dir, str(model_version))
    logger.info(f"Deleting model version {model_version} for {model_dir}")
    if os.path.exists(model_version_dir):
        shutil.rmtree(model_version_dir)


def get_edge_inference_service_name(detector_id: str, is_oodd: bool = False) -> str:
    """
    Kubernetes service/deployment names have a strict naming convention.
    They have to be alphanumeric, lower cased, and can only contain dashes.
    We just use `inferencemodel-{'oodd' or 'primary'}-<detector_id>` as the deployment name and
    `inference-service-{'oodd' or 'primary'}-<detector_id>` as the service name.
    """
    return f"inference-service-{'oodd' if is_oodd else 'primary'}-{detector_id.replace('_', '-').lower()}"


def get_edge_inference_deployment_name(detector_id: str, is_oodd: bool = False) -> str:
    return f"inferencemodel-{'oodd' if is_oodd else 'primary'}-{detector_id.replace('_', '-').lower()}"


def get_edge_inference_model_name(detector_id: str, is_oodd: bool = False) -> str:
    return os.path.join(detector_id, "primary" if not is_oodd else "oodd")


def get_detector_models_dir(repository_root: str, detector_id: str) -> str:
    return os.path.join(repository_root, detector_id)


def get_primary_edge_model_dir(repository_root: str, detector_id: str) -> str:
    return os.path.join(get_detector_models_dir(repository_root, detector_id), "primary")


def get_oodd_model_dir(repository_root: str, detector_id: str) -> str:
    return os.path.join(get_detector_models_dir(repository_root, detector_id), "oodd")
