"""Protocol details of the servers an inference pod can run: the FastAPI server or NVIDIA Triton.

Both serve the same model code from the gl-edge-inference images built in zuuul
(predictors/serving), so a Triton response carries the same JSON body as FastAPI's /infer.
The Triton names below are fixed by predictors/serving/triton/model_repository.py.
"""

import json
import os
import struct
from enum import Enum


class InferenceServer(str, Enum):
    FASTAPI = "fastapi"
    TRITON = "triton"


TRITON_MODEL_NAME = "edge_model"
TRITON_INPUT_NAME = "image"
TRITON_OUTPUT_NAME = "response"
TRITON_METRICS_PORT = 8002

READINESS_PATHS = {
    InferenceServer.FASTAPI: "/health/ready",
    InferenceServer.TRITON: "/v2/health/ready",
}

INFER_PATHS = {
    InferenceServer.FASTAPI: "/infer",
    InferenceServer.TRITON: f"/v2/models/{TRITON_MODEL_NAME}/infer",
}

# Pod template annotation recording which server an inference pod runs.
INFERENCE_SERVER_ANNOTATION = "groundlight.dev/inference-server"


def configured_inference_server() -> InferenceServer:
    """The server new inference pods are deployed with (Helm value `inferenceServer`)."""
    return InferenceServer(os.environ.get("INFERENCE_SERVER", InferenceServer.FASTAPI.value))


def encode_triton_infer_request(image_bytes: bytes) -> tuple[bytes, dict[str, str]]:
    """Return (body, headers) sending `image_bytes` as one BYTES tensor via the binary data extension."""
    header = json.dumps(
        {
            "inputs": [
                {
                    "name": TRITON_INPUT_NAME,
                    "shape": [1],
                    "datatype": "BYTES",
                    "parameters": {"binary_data_size": 4 + len(image_bytes)},
                }
            ],
            "outputs": [{"name": TRITON_OUTPUT_NAME, "parameters": {"binary_data": False}}],
        }
    ).encode()
    body = header + struct.pack("<I", len(image_bytes)) + image_bytes
    headers = {
        "Content-Type": "application/octet-stream",
        "Inference-Header-Content-Length": str(len(header)),
    }
    return body, headers


def decode_triton_infer_response(body: bytes) -> dict:
    """Return the model's JSON result from a Triton infer response with a JSON-encoded output."""
    outputs = [output for output in json.loads(body)["outputs"] if output["name"] == TRITON_OUTPUT_NAME]
    if len(outputs) != 1:
        raise ValueError(f"Expected one {TRITON_OUTPUT_NAME!r} output in the Triton response, got {len(outputs)}")
    (data,) = outputs[0]["data"]
    return json.loads(data)
