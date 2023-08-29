import logging

import numpy as np
import tritonclient.http as tritonclient
from tritonclient.http import InferenceServerClient

logger = logging.getLogger(__name__)

INPUT_IMAGE_NAME = "image"
OUTPUT_SCORE_NAME = "score"
OUTPUT_CONFIDENCE_NAME = "confidence"
OUTPUT_PROBABILITY_NAME = "probability"
INFERENCE_SERVER_URL = "inference-service:8000"


def is_edge_inference_available(inference_client: InferenceServerClient, model_name: str) -> bool:
    if not inference_client.is_server_live():
        logger.debug("Inference server is not live")
        return False
    if not inference_client.is_server_ready():
        logger.debug("Inference server is not ready")
        return False
    if not inference_client.is_model_ready(model_name):
        logger.debug(f"Inference model is not ready: {model_name}")
        return False
    return True


def edge_inference(inference_client: InferenceServerClient, img_numpy: np.ndarray, model_name: str) -> dict[str, float]:
    img_numpy = img_numpy.transpose(2, 0, 1)  # [H, W, C=3] -> [C=3, H, W]
    imginput = tritonclient.InferInput(INPUT_IMAGE_NAME, img_numpy.shape, datatype="UINT8")
    imginput.set_data_from_numpy(img_numpy)
    outputs = [tritonclient.InferRequestedOutput(f) for f in [OUTPUT_SCORE_NAME, OUTPUT_CONFIDENCE_NAME, OUTPUT_PROBABILITY_NAME]]

    response = inference_client.infer(
        model_name,
        inputs=[imginput],
        outputs=outputs,
        request_id="",
    )

    output_dict = {
        OUTPUT_SCORE_NAME: response.as_numpy(OUTPUT_SCORE_NAME)[0],
        OUTPUT_CONFIDENCE_NAME: response.as_numpy(OUTPUT_CONFIDENCE_NAME)[0],
        OUTPUT_PROBABILITY_NAME: response.as_numpy(OUTPUT_PROBABILITY_NAME)[0],
    }
    logger.debug(f"inference server response for model={model_name}: {output_dict}")
    return output_dict
