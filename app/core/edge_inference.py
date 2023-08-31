import logging

import numpy as np
import tritonclient.http as tritonclient
from tritonclient.http import InferenceServerClient

logger = logging.getLogger(__name__)

INPUT_IMAGE_NAME = "image"
OUTPUT_SCORE_NAME = "score"
OUTPUT_CONFIDENCE_NAME = "confidence"
OUTPUT_PROBABILITY_NAME = "probability"
OUTPUT_LABEL_NAME = "label"
INFERENCE_SERVER_URL = "inference-service:8000"


def edge_inference_is_available(
    inference_client: InferenceServerClient, model_name: str, model_version: str = ""
) -> bool:
    """
    Queries the inference server to see if everything is ready to perform inference.
    Args:
        inference_client: Inference server client object
        model_name: Name of the model to route to
        model_version: Version of the model to route to
    Returns:
        True if edge inference for the specified model is available, False otherwise
    """
    if not inference_client.is_server_live():
        logger.debug("Inference server is not live")
        return False
    if not inference_client.is_server_ready():
        logger.debug("Inference server is not ready")
        return False
    if not inference_client.is_model_ready(model_name, model_version=model_version):
        logger.debug(f"Inference model is not ready: {model_name}/{model_version}")
        return False
    return True


def edge_inference(
    inference_client: InferenceServerClient, img_numpy: np.ndarray, model_name: str, model_version: str = ""
) -> dict:
    """
    Submit an image to the inference server, route to a specific model, and return the results.
    Args:
        inference_client: Inference server client object
        img_numpy: Image as a numpy array (assumes HWC uint8 RGB image)
        model_name: Name of the model to route to
        model_version: Version of the model to route to
    Returns:
        Dictionary of inference results with keys:
            - "score": float
            - "confidence": float
            - "probability": float
            - "label": str
    """
    img_numpy = img_numpy.transpose(2, 0, 1)  # [H, W, C=3] -> [C=3, H, W]
    imginput = tritonclient.InferInput(INPUT_IMAGE_NAME, img_numpy.shape, datatype="UINT8")
    imginput.set_data_from_numpy(img_numpy)
    outputs = [
        tritonclient.InferRequestedOutput(f)
        for f in [OUTPUT_SCORE_NAME, OUTPUT_CONFIDENCE_NAME, OUTPUT_PROBABILITY_NAME]
    ]

    logger.debug("Submitting image to edge inference service")
    response = inference_client.infer(
        model_name,
        model_version=model_version,
        inputs=[imginput],
        outputs=outputs,
        request_id="",
    )

    probability = response.as_numpy(OUTPUT_PROBABILITY_NAME)[0]
    output_dict = {
        OUTPUT_SCORE_NAME: response.as_numpy(OUTPUT_SCORE_NAME)[0],
        OUTPUT_CONFIDENCE_NAME: response.as_numpy(OUTPUT_CONFIDENCE_NAME)[0],
        OUTPUT_PROBABILITY_NAME: probability,
        OUTPUT_LABEL_NAME: _probability_to_label(probability),
    }
    logger.debug(f"Inference server response for model={model_name}: {output_dict}")
    return output_dict


def _probability_to_label(prob: float) -> str:
    # TODO: there is a way to get the label string from the inference server. Do that instead.
    return "YES" if prob < 0.5 else "NO"
