from contextlib import contextmanager
from datetime import datetime
from unittest import mock

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from model import (
    BinaryClassificationResult,
    Detector,
    DetectorTypeEnum,
    EscalationTypeEnum,
    ImageQuery,
    ImageQueryTypeEnum,
    Label,
    ModeEnum,
    ResultTypeEnum,
    Source,
)
from PIL import Image

from app.api.api import IMAGE_QUERIES
from app.api.naming import full_path
from app.core.utils import pil_image_to_bytes

url = full_path(IMAGE_QUERIES)

DETECTOR_ID = "det_abcdefghijklmnopqrstuvwxyz"


# TODO: Add missing tests for the following functionality:
# 1. Edge inference is available, runs and is confident / not confident
# 2. always_return_edge_prediction == True
# 3. Inference-deployment record created in DB if one doesn't already exist


@pytest.fixture
def detector() -> Detector:
    """Retrieve a faked Detector."""
    return Detector(
        id=DETECTOR_ID,
        type=DetectorTypeEnum.detector,
        created_at=datetime(2024, 10, 6, 7, 35, 0),
        name="test_detector",
        query="Where is my super suit?",
        group_name="test_group",
        confidence_threshold=0.75,
        patience_time=30,
        metadata=None,
        mode=ModeEnum.BINARY,
        mode_configuration=None,
        escalation_type=EscalationTypeEnum.STANDARD,
    )


confident_cloud_iq = ImageQuery(
    metadata=None,
    id="iq_123456789",
    type=ImageQueryTypeEnum.image_query,
    created_at=datetime(2024, 10, 6, 9, 35, 0),
    query="",
    detector_id=DETECTOR_ID,
    result_type=ResultTypeEnum.binary_classification,
    result=BinaryClassificationResult(confidence=1.0, label=Label.YES, source=Source.CLOUD),
    confidence_threshold=0.75,
    patience_time=30,
    rois=None,
    text=None,
)


@contextmanager
def assert_escalated_to_gl(*, sdk_response: ImageQuery, detector: Detector, submitted_with: dict | None = None):
    """
    Context manager to assert that an image query is escalated to the Groundlight SDK.

    This function patches the `submit_image_query` method of the Groundlight SDK to return
    a predefined response (`sdk_response`). It yields the mocked method to allow further
    assertions on how it was called. Use `submitted_with` to assert that a subset of the
    arguments used to escalate to the cloud are as expected.
    """
    with mock.patch("app.api.routes.image_queries.Groundlight.get_detector") as mock_get_detector:
        mock_get_detector.return_value = detector

        with mock.patch("app.api.routes.image_queries.Groundlight.submit_image_query") as mock_submit:
            mock_submit.return_value = sdk_response
            yield mock_submit

            if submitted_with:
                mock_submit.assert_called_once_with(
                    *[mock.ANY for v in mock_submit.call_args.args],
                    **{k: v if k in submitted_with else mock.ANY for k, v in mock_submit.call_args.kwargs.items()},
                )
            else:
                mock_submit.assert_called_once()


@contextmanager
def assert_not_escalated_to_gl(detector: Detector | None = None):
    """Context manager to assert that an image query is NOT escalated to the Groundlight SDK."""
    if detector is None:  # no detector provided, for invalid detector_id test
        with mock.patch("app.api.routes.image_queries.Groundlight.submit_image_query") as mock_submit:
            yield mock_submit
            mock_submit.assert_not_called()
    else:
        with mock.patch("app.api.routes.image_queries.Groundlight.get_detector") as mock_get_detector:
            mock_get_detector.return_value = detector
            with mock.patch("app.api.routes.image_queries.Groundlight.submit_image_query") as mock_submit:
                yield mock_submit
                mock_submit.assert_not_called()


@contextmanager
def enable_edge_inference(
    *, edge_response: dict | None = None, assert_ran: bool = False, assert_didnt_run: bool = False
):
    """
    Context manager to mock everything for supporting edge inference. Returns that edge_inference
    is available (as if the inference deployment is ready), and enables/requires the user to specify
    the exact contents of the edge_response.
    # TODO: better mocking support for edge_response
    """
    if assert_ran and assert_didnt_run:
        raise ValueError("Conflicting assertions configured.")
    edge_response = edge_response or {}

    mock_edge_inference_manager = mock.Mock()
    mock_edge_inference_manager.inference_is_available.return_value = True
    mock_edge_inference_manager.run_inference.return_value = edge_response

    # We need to inject the edge_inference_manager mock via `get_app_state`, so
    # we need to mock AppState as well. It would be nicer if we had more loosely
    # coupled dependency injection here.
    mock_app_state = mock.Mock()
    mock_app_state.edge_inference_manager = mock_edge_inference_manager

    with mock.patch("app.api.routes.image_queries.get_app_state") as mock_app_state:
        yield mock_edge_inference_manager

        if assert_ran:  # assert that a request was sent to the inference server
            mock_edge_inference_manager.inference_is_available.assert_called_once()
        if assert_didnt_run:
            mock_edge_inference_manager.inference_is_available.assert_not_called()


#
# Tests for successful requests:
#


def test_post_image_query(test_client: TestClient, detector: Detector):
    """Test that submitting an image query using the edge server proceeds without failure."""
    image_bytes = pil_image_to_bytes(img=Image.open("test/assets/dog.jpeg"))
    threshold = 0.87

    with assert_escalated_to_gl(
        submitted_with={"confidence_threshold": threshold}, detector=detector, sdk_response=confident_cloud_iq
    ):
        with enable_edge_inference(assert_didnt_run=True):  # No inference deployments configured yet
            response = test_client.post(
                url,
                headers={"Content-Type": "image/jpeg"},
                content=image_bytes,
                params={"confidence_threshold": threshold, "detector_id": detector.id},
            )

            assert response.status_code == status.HTTP_200_OK, response.json()["detail"]
            response_data = response.json()
            assert "id" in response_data, "Response should contain an 'id' field"


def test_post_image_query_with_async_request(test_client: TestClient, detector: Detector):
    """Test submitting an image query with want_async set to true."""
    image_bytes = pil_image_to_bytes(img=Image.open("test/assets/dog.jpeg"))

    with assert_escalated_to_gl(
        submitted_with={"want_async": True}, detector=detector, sdk_response=confident_cloud_iq
    ):
        response = test_client.post(
            url,
            headers={"Content-Type": "image/jpeg"},
            content=image_bytes,
            params={"confidence_threshold": 1.0, "want_async": True, "detector_id": detector.id},
        )
        assert response.status_code == status.HTTP_200_OK, response.json()["detail"]
        response_data = response.json()
        assert "id" in response_data, "Response should contain an 'id' field"


def test_post_image_query_with_confident_audit(test_client: TestClient, detector: Detector):
    """Test submitting an image query that should be audited."""
    image_bytes = pil_image_to_bytes(img=Image.open("test/assets/dog.jpeg"))

    with assert_escalated_to_gl(
        submitted_with={"metadata": {"is_edge_audit": True}},
        detector=detector,
        sdk_response=confident_cloud_iq,
    ):
        with enable_edge_inference(edge_response={"confidence": 0.95, "label": 0, "text": None, "rois": None}):
            with mock.patch("app.api.routes.image_queries.get_app_state") as mock_get_app_state:
                # Guarantee an audit
                mock_get_app_state.return_value.edge_config.global_config.confident_audit_rate = 1.0
                response = test_client.post(
                    url,
                    headers={"Content-Type": "image/jpeg"},
                    content=image_bytes,
                    params={"detector_id": detector.id},
                )

            assert response.status_code == status.HTTP_200_OK, response.json()["detail"]


# TODO: This test doesn't seem to actually test this behavior, since it was passing when it should have failed.
# It should get removed once this behavior is tested in the live environment.
def test_post_image_query_with_human_review(test_client: TestClient, detector: Detector):
    """Test submitting an image query with human review set to ALWAYS."""
    image_bytes = pil_image_to_bytes(img=Image.open("test/assets/dog.jpeg"))

    with assert_escalated_to_gl(
        submitted_with={"human_review": "ALWAYS"}, detector=detector, sdk_response=confident_cloud_iq
    ):
        # Dont run edge inference if human review is requested
        with enable_edge_inference(assert_didnt_run=True):
            response = test_client.post(
                url,
                headers={"Content-Type": "image/jpeg"},
                content=image_bytes,
                params={"confidence_threshold": 1.0, "human_review": "ALWAYS", "detector_id": detector.id},
            )

            assert response.status_code == status.HTTP_200_OK, response.json()["detail"]
            response_data = response.json()
            assert "id" in response_data, "Response should contain an 'id' field"


#
# Tests for invalid requests:
#


def test_post_image_query_invalid_content_type(test_client: TestClient, detector: Detector):
    """Test submitting an image query with an invalid content type."""
    with assert_not_escalated_to_gl(detector=detector):
        response = test_client.post(
            url,
            headers={"Content-Type": "text/plain"},  # unsupported
            content=b"not an image",
            params={"detector_id": detector.id},
        )
        assert response.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, response.json()["detail"]
        assert response.json() == {"detail": "Request body must be image bytes"}


def test_post_image_query_invalid_image_data(test_client: TestClient, detector: Detector):
    """Test submitting an image query with invalid image data."""
    with assert_not_escalated_to_gl(detector=detector):
        response = test_client.post(
            url,
            headers={"Content-Type": "image/jpeg"},
            content=b"not an image",  # not a jpeg binary
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY, response.json()["detail"]


@pytest.mark.xfail(reason="Known issue - 404 is not returned when detector is not found")
def test_post_image_query_with_invalid_detector_id(test_client: TestClient, detector: Detector):
    """Test submitting an image query with an invalid detector ID."""
    image_bytes = pil_image_to_bytes(img=Image.open("test/assets/dog.jpeg"))

    with assert_not_escalated_to_gl(detector=None):
        response = test_client.post(
            url,
            headers={"Content-Type": "image/jpeg"},
            content=image_bytes,
            params={
                "detector_id": "invalid_id",  # wont resolve to a detector
                "confidence_threshold": 1.0,
            },
        )

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.json()["detail"]
    assert response.json() == {"detail": "Detector with id 'invalid_id' not found"}


def test_post_image_query_with_invalid_field(test_client: TestClient, detector: Detector):
    """Test submitting an image query with an invalid detector ID."""
    image_bytes = pil_image_to_bytes(img=Image.open("test/assets/dog.jpeg"))

    with assert_not_escalated_to_gl(detector=detector):
        response = test_client.post(
            url,
            headers={"Content-Type": "image/jpeg"},
            content=image_bytes,
            params={
                "confidence_threshold": 1.0,
                "detector_id": detector.id,
                "inspection_id": "insp_id",  # inspections not supported on edge
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()["detail"]
        assert "inspection_id" in response.json()["detail"]
