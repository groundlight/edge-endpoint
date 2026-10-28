import json
import struct

import pytest

from app.core.inference_server import (
    TRITON_INPUT_NAME,
    TRITON_OUTPUT_NAME,
    InferenceServer,
    configured_inference_server,
    decode_triton_infer_response,
    encode_triton_infer_request,
)


def test_encode_triton_infer_request_uses_the_binary_data_extension():
    image = b"\xff\xd8jpeg-bytes"

    body, headers = encode_triton_infer_request(image)

    header_length = int(headers["Inference-Header-Content-Length"])
    header = json.loads(body[:header_length])
    assert header["inputs"] == [
        {
            "name": TRITON_INPUT_NAME,
            "shape": [1],
            "datatype": "BYTES",
            "parameters": {"binary_data_size": 4 + len(image)},
        }
    ]
    assert header["outputs"] == [{"name": TRITON_OUTPUT_NAME, "parameters": {"binary_data": False}}]
    assert body[header_length:] == struct.pack("<I", len(image)) + image
    assert headers["Content-Type"] == "application/octet-stream"


def test_decode_triton_infer_response_returns_the_model_json():
    result = {"predictions": {"confidences": [0.9], "labels": [1]}, "multi_predictions": None}
    body = json.dumps(
        {
            "model_name": "edge_model",
            "outputs": [{"name": TRITON_OUTPUT_NAME, "datatype": "BYTES", "shape": [1], "data": [json.dumps(result)]}],
        }
    ).encode()

    assert decode_triton_infer_response(body) == result


def test_decode_triton_infer_response_requires_the_response_output():
    body = json.dumps({"outputs": [{"name": "other", "data": ["{}"]}]}).encode()

    with pytest.raises(ValueError, match="Expected one 'response' output"):
        decode_triton_infer_response(body)


def test_configured_inference_server_defaults_to_fastapi(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("INFERENCE_SERVER", raising=False)
    assert configured_inference_server() is InferenceServer.FASTAPI


def test_configured_inference_server_reads_the_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("INFERENCE_SERVER", "triton")
    assert configured_inference_server() is InferenceServer.TRITON


def test_configured_inference_server_rejects_unknown_values(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("INFERENCE_SERVER", "grpc")
    with pytest.raises(ValueError):
        configured_inference_server()
