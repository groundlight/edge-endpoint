import pytest
from model import ModeEnum

from app.core.edge_inference import adjust_confidence_with_oodd


@pytest.fixture
def mock_parsed_binary_response():
    return {
        "confidence": 0.8,
        "label": 0,
        "text": None,
        "rois": None,
    }


@pytest.fixture
def mock_parsed_count_response():
    return {
        "probabilities": [0.1, 0.6, 0.2, 0.1],
        "confidence": 0.6,
        "label": 1,
        "text": "This is a bird.",
        "rois": [
            {
                "geometry": {"x": 0.2, "y": 0.3, "left": 0.1, "top": 0.2, "right": 0.3, "bottom": 0.4},
                "label": "bird",
                "score": 0.9,
                "version": "2.0",
            }
        ],
    }


@pytest.fixture
def mock_parsed_multiclass_response():
    return {
        "probabilities": [0.1, 0.7, 0.1, 0.05, 0.05],
        "confidence": 0.7,
        "label": 1,
        "text": None,
        "rois": None,
    }


@pytest.fixture
def mock_parsed_bounding_box_response():
    return {
        "probabilities": [0, 1, 0],
        "confidence": 0.6,
        "label": 1,
        "text": "This is a bird.",
        "rois": [
            {
                "geometry": {"x": 0.2, "y": 0.3, "left": 0.1, "top": 0.2, "right": 0.3, "bottom": 0.4},
                "label": "bird",
                "score": 0.9,
                "version": "2.0",
            }
        ],
    }


@pytest.fixture
def mock_outlier_oodd_response():
    return {
        "confidence": 0.9,
        "label": 1,
    }


@pytest.fixture
def mock_inlier_oodd_response():
    return {
        "confidence": 0.95,
        "label": 0,
    }


def test_adjust_confidence_with_oodd_binary(
    mock_parsed_binary_response, mock_outlier_oodd_response, mock_inlier_oodd_response
):
    num_classes = 2
    adjusted_output_dict = adjust_confidence_with_oodd(
        primary_output_dict=mock_parsed_binary_response,
        oodd_output_dict=mock_outlier_oodd_response,
        mode=ModeEnum.BINARY,
        num_classes=num_classes,
    )
    assert adjusted_output_dict["confidence"] == 0.53
    assert adjusted_output_dict["label"] == 0
    assert adjusted_output_dict["text"] is None
    assert adjusted_output_dict["rois"] is None

    adjusted_output_dict = adjust_confidence_with_oodd(
        primary_output_dict=mock_parsed_binary_response,
        oodd_output_dict=mock_inlier_oodd_response,
        mode=ModeEnum.BINARY,
        num_classes=num_classes,
    )
    assert adjusted_output_dict["confidence"] == 0.785
    assert adjusted_output_dict["label"] == 0
    assert adjusted_output_dict["text"] is None
    assert adjusted_output_dict["rois"] is None


def test_adjust_confidence_with_oodd_count(
    mock_parsed_count_response, mock_outlier_oodd_response, mock_inlier_oodd_response
):
    num_classes = 4
    adjusted_output_dict = adjust_confidence_with_oodd(
        primary_output_dict=mock_parsed_count_response,
        oodd_output_dict=mock_outlier_oodd_response,
        mode=ModeEnum.COUNT,
        num_classes=num_classes,
    )
    assert adjusted_output_dict["confidence"] == 0.285

    assert adjusted_output_dict["label"] == 1
    assert adjusted_output_dict["text"] == "This is a bird."
    assert len(adjusted_output_dict["rois"]) == 1
    assert adjusted_output_dict["rois"][0]["label"] == "bird"
    assert adjusted_output_dict["rois"][0]["score"] == 0.9
    assert adjusted_output_dict["rois"][0]["version"] == "2.0"
    assert adjusted_output_dict["rois"][0]["geometry"] == {
        "x": 0.2,
        "y": 0.3,
        "left": 0.1,
        "top": 0.2,
        "right": 0.3,
        "bottom": 0.4,
    }

    adjusted_output_dict = adjust_confidence_with_oodd(
        primary_output_dict=mock_parsed_count_response,
        oodd_output_dict=mock_inlier_oodd_response,
        mode=ModeEnum.COUNT,
        num_classes=num_classes,
    )
    assert adjusted_output_dict["confidence"] == 0.5825
    assert adjusted_output_dict["label"] == 1
    assert adjusted_output_dict["text"] == "This is a bird."
    assert len(adjusted_output_dict["rois"]) == 1
    assert adjusted_output_dict["rois"][0]["label"] == "bird"
    assert adjusted_output_dict["rois"][0]["score"] == 0.9
    assert adjusted_output_dict["rois"][0]["version"] == "2.0"
    assert adjusted_output_dict["rois"][0]["geometry"] == {
        "x": 0.2,
        "y": 0.3,
        "left": 0.1,
        "top": 0.2,
        "right": 0.3,
        "bottom": 0.4,
    }


def test_adjust_confidence_with_oodd_multiclass(
    mock_parsed_multiclass_response, mock_outlier_oodd_response, mock_inlier_oodd_response
):
    num_classes = 5
    adjusted_output_dict = adjust_confidence_with_oodd(
        primary_output_dict=mock_parsed_multiclass_response,
        oodd_output_dict=mock_outlier_oodd_response,
        mode=ModeEnum.MULTI_CLASS,
        num_classes=num_classes,
    )
    assert adjusted_output_dict["confidence"] == pytest.approx(0.25)
    assert adjusted_output_dict["label"] == 1
    assert adjusted_output_dict["text"] is None
    assert adjusted_output_dict["rois"] is None

    adjusted_output_dict = adjust_confidence_with_oodd(
        primary_output_dict=mock_parsed_multiclass_response,
        oodd_output_dict=mock_inlier_oodd_response,
        mode=ModeEnum.MULTI_CLASS,
        num_classes=num_classes,
    )
    assert adjusted_output_dict["confidence"] == pytest.approx(0.675)
    assert adjusted_output_dict["label"] == 1
    assert adjusted_output_dict["text"] is None
    assert adjusted_output_dict["rois"] is None


def test_adjust_confidence_with_oodd_bounding_box(
    mock_parsed_bounding_box_response, mock_outlier_oodd_response, mock_inlier_oodd_response
):
    num_classes = 3
    adjusted_output_dict = adjust_confidence_with_oodd(
        primary_output_dict=mock_parsed_bounding_box_response,
        oodd_output_dict=mock_outlier_oodd_response,
        mode=ModeEnum.BOUNDING_BOX,
        num_classes=num_classes,
    )
    assert adjusted_output_dict["confidence"] == pytest.approx(0.06)

    assert adjusted_output_dict["label"] == 1
    assert adjusted_output_dict["text"] == "This is a bird."
    assert len(adjusted_output_dict["rois"]) == 1
    assert adjusted_output_dict["rois"][0]["label"] == "bird"
    assert adjusted_output_dict["rois"][0]["score"] == 0.9
    assert adjusted_output_dict["rois"][0]["version"] == "2.0"
    assert adjusted_output_dict["rois"][0]["geometry"] == {
        "x": 0.2,
        "y": 0.3,
        "left": 0.1,
        "top": 0.2,
        "right": 0.3,
        "bottom": 0.4,
    }

    adjusted_output_dict = adjust_confidence_with_oodd(
        primary_output_dict=mock_parsed_bounding_box_response,
        oodd_output_dict=mock_inlier_oodd_response,
        mode=ModeEnum.BOUNDING_BOX,
        num_classes=num_classes,
    )
    assert adjusted_output_dict["confidence"] == pytest.approx(0.57)
    assert adjusted_output_dict["label"] == 1
    assert adjusted_output_dict["text"] == "This is a bird."
    assert len(adjusted_output_dict["rois"]) == 1
    assert adjusted_output_dict["rois"][0]["label"] == "bird"
    assert adjusted_output_dict["rois"][0]["score"] == 0.9
    assert adjusted_output_dict["rois"][0]["version"] == "2.0"
    assert adjusted_output_dict["rois"][0]["geometry"] == {
        "x": 0.2,
        "y": 0.3,
        "left": 0.1,
        "top": 0.2,
        "right": 0.3,
        "bottom": 0.4,
    }
