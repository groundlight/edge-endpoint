import json
from unittest import mock

import pytest
import requests

from app.core import edge_inference
from app.core.edge_inference import get_ready_inference_server, is_edge_inference_ready, submit_image_for_inference
from app.core.inference_server import TRITON_OUTPUT_NAME, InferenceServer

URL = "inference-service-primary-det-abc:8000"
RESULT = {
    "predictions": {"confidences": [0.9], "labels": [1]},
    "multi_predictions": None,
    "secondary_predictions": None,
}


def response(status_code: int, body: bytes = b"") -> mock.Mock:
    return mock.Mock(status_code=status_code, content=body, text=body.decode(), json=lambda: json.loads(body))


def triton_body(result: dict) -> bytes:
    return json.dumps({"outputs": [{"name": TRITON_OUTPUT_NAME, "data": [json.dumps(result)]}]}).encode()


@pytest.fixture(autouse=True)
def clear_readiness_cache():
    edge_inference.ttl_cache.clear()
    yield
    edge_inference.ttl_cache.clear()


def test_detects_a_ready_triton_pod(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("INFERENCE_SERVER", "triton")
    with mock.patch.object(edge_inference.requests, "get", return_value=response(200)) as get:
        assert get_ready_inference_server(URL) is InferenceServer.TRITON

    get.assert_called_once_with(f"http://{URL}/v2/health/ready", timeout=2)


def test_falls_back_to_a_fastapi_pod_that_has_not_rolled_to_triton(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("INFERENCE_SERVER", "triton")
    with mock.patch.object(edge_inference.requests, "get", side_effect=[response(404), response(200)]) as get:
        assert get_ready_inference_server(URL) is InferenceServer.FASTAPI

    assert [c.args[0] for c in get.call_args_list] == [f"http://{URL}/v2/health/ready", f"http://{URL}/health/ready"]


def test_probes_fastapi_first_by_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("INFERENCE_SERVER", raising=False)
    with mock.patch.object(edge_inference.requests, "get", return_value=response(200)) as get:
        assert get_ready_inference_server(URL) is InferenceServer.FASTAPI

    get.assert_called_once_with(f"http://{URL}/health/ready", timeout=2)


def test_a_pod_that_is_not_ready_on_either_server_is_not_ready(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("INFERENCE_SERVER", raising=False)
    with mock.patch.object(edge_inference.requests, "get", side_effect=[response(503), response(404)]):
        assert get_ready_inference_server(URL) is None
    assert not is_edge_inference_ready(URL)


def test_an_unreachable_pod_is_not_ready(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("INFERENCE_SERVER", raising=False)
    with mock.patch.object(
        edge_inference.requests, "get", side_effect=requests.exceptions.ConnectionError("refused")
    ) as get:
        assert not is_edge_inference_ready(URL)

    assert get.call_count == 1


def test_submits_to_triton_with_its_tensor_protocol(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("INFERENCE_SERVER", "triton")
    with (
        mock.patch.object(edge_inference.requests, "get", return_value=response(200)),
        mock.patch.object(edge_inference.requests, "post", return_value=response(200, triton_body(RESULT))) as post,
    ):
        assert submit_image_for_inference(URL, b"jpeg", "image/jpeg") == RESULT

    assert post.call_args.args[0] == f"http://{URL}/v2/models/edge_model/infer"
    headers = post.call_args.kwargs["headers"]
    assert headers["Content-Type"] == "application/octet-stream"
    assert post.call_args.kwargs["data"].endswith(b"\x04\x00\x00\x00jpeg")


def test_submits_to_fastapi_with_the_raw_image(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("INFERENCE_SERVER", raising=False)
    with (
        mock.patch.object(edge_inference.requests, "get", return_value=response(200)),
        mock.patch.object(
            edge_inference.requests, "post", return_value=response(200, json.dumps(RESULT).encode())
        ) as post,
    ):
        assert submit_image_for_inference(URL, b"jpeg", "image/jpeg") == RESULT

    post.assert_called_once_with(f"http://{URL}/infer", data=b"jpeg", headers={"Content-Type": "image/jpeg"})


def test_raises_when_triton_rejects_the_request(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("INFERENCE_SERVER", "triton")
    with (
        mock.patch.object(edge_inference.requests, "get", return_value=response(200)),
        mock.patch.object(
            edge_inference.requests, "post", return_value=response(400, b'{"error": "Invalid image"}')
        ) as post,
    ):
        with pytest.raises(RuntimeError, match="Inference server error: 400"):
            submit_image_for_inference(URL, b"not an image", "image/jpeg")

    post.assert_called_once()


def test_retries_with_the_other_protocol_when_the_route_is_missing(monkeypatch: pytest.MonkeyPatch):
    """While a detector moves between servers, its Service can route to a pod still running the other one."""
    monkeypatch.setenv("INFERENCE_SERVER", "triton")
    with (
        mock.patch.object(edge_inference.requests, "get", return_value=response(200)),
        mock.patch.object(
            edge_inference.requests,
            "post",
            side_effect=[response(404, b'{"detail": "Not Found"}'), response(200, json.dumps(RESULT).encode())],
        ) as post,
    ):
        assert submit_image_for_inference(URL, b"jpeg", "image/jpeg") == RESULT

    assert [c.args[0] for c in post.call_args_list] == [
        f"http://{URL}/v2/models/edge_model/infer",
        f"http://{URL}/infer",
    ]
    assert post.call_args.kwargs == {"data": b"jpeg", "headers": {"Content-Type": "image/jpeg"}}
