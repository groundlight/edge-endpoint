import logging
import socket
import time
from typing import Dict

import numpy as np
import tritonclient.http as tritonclient

from .configs import LocalInferenceConfig

logger = logging.getLogger(__name__)


class EdgeInferenceManager:
    INPUT_IMAGE_NAME = "image"
    OUTPUT_SCORE_NAME = "score"
    OUTPUT_CONFIDENCE_NAME = "confidence"
    OUTPUT_PROBABILITY_NAME = "probability"
    OUTPUT_LABEL_NAME = "label"
    INFERENCE_SERVER_URL = "inference-service:8000"

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

    def inference_is_available(self, detector_id: str) -> bool:
        """
        Queries the inference server to see if everything is ready to perform inference.
        Args:
            detector_id: ID of the detector on which to run local edge inference
        Returns:
            True if edge inference for the specified detector is available, False otherwise
        """
        if detector_id not in self.inference_config.keys():
            logger.info(f"Edge inference is not enabled for {detector_id=}")
            return False

        model_name, model_version = (
            self.inference_config[detector_id].model_name,
            self.inference_config[detector_id].model_version,
        )

        try:
            if not self.inference_client.is_server_live():
                logger.debug("Edge inference server is not live")
                return False
            if not self.inference_client.is_server_ready():
                logger.debug("Edge inference server is not ready")
                return False
            if not self.inference_client.is_model_ready(model_name, model_version=model_version):
                logger.debug(f"Edge inference model is not ready: {model_name}/{model_version}")
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
        outputs = [
            tritonclient.InferRequestedOutput(f)
            for f in [self.OUTPUT_SCORE_NAME, self.OUTPUT_CONFIDENCE_NAME, self.OUTPUT_PROBABILITY_NAME]
        ]

        model_name, model_version = (
            self.inference_config[detector_id].model_name,
            self.inference_config[detector_id].model_version,
        )

        logger.debug("Submitting image to edge inference service")
        start = time.monotonic()
        response = self.inference_client.infer(
            model_name,
            model_version=model_version,
            inputs=[imginput],
            outputs=outputs,
            request_id="",
        )
        end = time.monotonic()

        probability = response.as_numpy(self.OUTPUT_PROBABILITY_NAME)[0]
        output_dict = {
            self.OUTPUT_SCORE_NAME: response.as_numpy(self.OUTPUT_SCORE_NAME)[0],
            self.OUTPUT_CONFIDENCE_NAME: response.as_numpy(self.OUTPUT_CONFIDENCE_NAME)[0],
            self.OUTPUT_PROBABILITY_NAME: probability,
            self.OUTPUT_LABEL_NAME: self._probability_to_label(probability),
        }
        logger.debug(
            f"Inference server response for model={model_name}: {output_dict}Inference time: {end - start:.2f} seconds"
        )
        return output_dict

    def _probability_to_label(self, prob: float) -> str:
        # TODO: there is a way to get the label string from the inference server. Do that instead.
        return "YES" if prob < 0.5 else "NO"
