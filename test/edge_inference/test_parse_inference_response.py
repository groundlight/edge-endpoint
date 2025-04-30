import pytest

from app.core.edge_inference import parse_inference_response


# Fixtures for mock responses
@pytest.fixture
def mock_binary_response():
    return {
        "multi_predictions": None,
        "predictions": {"confidences": [0.54], "labels": [0], "probabilities": [0.45], "scores": [-2.94]},
        "secondary_predictions": None,
    }


@pytest.fixture
def mock_count_response():
    return {
        "multi_predictions": {
            "labels": [[0, 1, 0, 0]],
            "probabilities": [[0.1, 0.6, 0.2, 0.1]],
        },
        "predictions": None,
        "secondary_predictions": {
            "roi_predictions": {
                "rois": [
                    [
                        {
                            "label": "bird",
                            "geometry": {"left": 0.1, "top": 0.2, "right": 0.3, "bottom": 0.4, "version": "2.0"},
                            "score": 0.9,
                            "version": "2.0",
                        }
                    ]
                ]
            },
            "text_predictions": ["This is a bird."],
        },
    }


@pytest.fixture
def mock_multiclass_response():
    return {
        "multi_predictions": {
            "labels": [[0.0, 1.0, 0.0, 0.0]],
            "probabilities": [[0.03, 0.90, 0.01, 0.03]],
            "rois": None,
            "text": None,
            "ignore_prob_sum": False,
        },
        "predictions": None,
        "secondary_predictions": None,
    }


@pytest.fixture
def mock_binary_with_rois_response():
    return {
        "multi_predictions": None,
        "predictions": {"confidences": [0.54], "labels": [0], "probabilities": [0.45], "scores": [-2.94]},
        "secondary_predictions": {
            "roi_predictions": {
                "rois": [
                    [
                        {
                            "label": "cat",
                            "geometry": {"left": 0.1, "top": 0.2, "right": 0.3, "bottom": 0.4, "version": "2.0"},
                            "score": 0.8,
                            "version": "2.0",
                        },
                        {
                            "label": "cat",
                            "geometry": {"left": 0.6, "top": 0.7, "right": 0.8, "bottom": 0.9, "version": "2.0"},
                            "score": 0.7,
                            "version": "2.0",
                        },
                    ]
                ]
            },
            "text_predictions": None,
        },
    }


@pytest.fixture
def mock_binary_with_text_response():
    return {
        "multi_predictions": None,
        "predictions": {"confidences": [0.54], "labels": [0], "probabilities": [0.45], "scores": [-2.94]},
        "secondary_predictions": {
            "roi_predictions": None,
            "text_predictions": ["This is a cat."],
        },
    }


@pytest.fixture
def mock_invalid_predictions_response():
    return {
        "multi_predictions": {
            "labels": [[0, 1, 0, 0]],
            "probabilities": [[0.1, 0.6, 0.2, 0.1]],
        },
        "predictions": {"confidences": [0.54], "labels": [0], "probabilities": [0.45], "scores": [-2.94]},
        "secondary_predictions": {
            "roi_predictions": {
                "rois": [
                    [
                        {
                            "label": "bird",
                            "geometry": {"left": 0.1, "top": 0.2, "right": 0.3, "bottom": 0.4, "version": "2.0"},
                            "score": 0.9,
                            "version": "2.0",
                        }
                    ]
                ]
            },
            "text_predictions": None,
        },
    }


@pytest.fixture
def mock_invalid_predictions_missing_response():
    return {
        "multi_predictions": None,
        "predictions": None,
        "secondary_predictions": {
            "roi_predictions": {
                "rois": [
                    [
                        {
                            "label": "bird",
                            "geometry": {"left": 0.1, "top": 0.2, "right": 0.3, "bottom": 0.4, "version": "2.0"},
                            "score": 0.9,
                            "version": "2.0",
                        }
                    ]
                ]
            },
            "text_predictions": None,
        },
    }


@pytest.fixture
def mock_invalid_predictions_invalid_text():
    return {
        "multi_predictions": None,
        "predictions": {"confidences": [0.54], "labels": [0], "probabilities": [0.45], "scores": [-2.94]},
        "secondary_predictions": {
            "roi_predictions": None,
            "text_predictions": ["This is a cat", "This is too many text predictions"],
        },
    }


class TestParseInferenceResponse:
    def test_parse_binary_response(self, mock_binary_response):
        result = parse_inference_response(mock_binary_response)
        assert result["confidence"] == 0.54
        assert result["label"] == 0
        assert result["text"] is None
        assert result["rois"] is None

    def test_parse_count_response(self, mock_count_response):
        result = parse_inference_response(mock_count_response)
        assert result["confidence"] == 0.6
        assert result["label"] == 1
        assert result["text"] == "This is a bird."
        assert len(result["rois"]) == 1
        assert result["rois"][0]["label"] == "bird"
        assert result["rois"][0]["score"] == 0.9
        assert "x" in result["rois"][0]["geometry"]
        assert "y" in result["rois"][0]["geometry"]
    
    def test_parse_multiclass_response(self, mock_multiclass_response):
        result = parse_inference_response(mock_multiclass_response)
        assert result["confidence"] == 0.90
        assert result["label"] == 1
        assert result["text"] is None
        assert result["rois"] is None

    def test_parse_binary_with_rois_response(self, mock_binary_with_rois_response):
        result = parse_inference_response(mock_binary_with_rois_response)
        assert result["confidence"] == 0.54
        assert result["label"] == 0
        assert result["text"] is None
        assert len(result["rois"]) == 2
        assert result["rois"][0]["label"] == "cat"
        assert result["rois"][0]["score"] == 0.8
        assert "x" in result["rois"][0]["geometry"]
        assert "y" in result["rois"][0]["geometry"]
        assert result["rois"][1]["label"] == "cat"
        assert result["rois"][1]["score"] == 0.7
        assert "x" in result["rois"][1]["geometry"]
        assert "y" in result["rois"][1]["geometry"]

        assert result["rois"][0]["geometry"]["x"] != result["rois"][1]["geometry"]["x"]
        assert result["rois"][0]["geometry"]["y"] != result["rois"][1]["geometry"]["y"]

    def test_parse_binary_with_text_response(self, mock_binary_with_text_response):
        result = parse_inference_response(mock_binary_with_text_response)
        assert result["confidence"] == 0.54
        assert result["label"] == 0
        assert result["text"] == "This is a cat."
        assert result["rois"] is None

    def test_parse_invalid_response(self, mock_invalid_predictions_response):
        with pytest.raises(ValueError, match="Got result with both multi_predictions and predictions"):
            parse_inference_response(mock_invalid_predictions_response)

    def test_parse_invalid_response_predictions_missing(self, mock_invalid_predictions_missing_response):
        with pytest.raises(ValueError, match="Got result with no multi_predictions or predictions"):
            parse_inference_response(mock_invalid_predictions_missing_response)

    def test_parse_invalid_response_invalid_text(self, mock_invalid_predictions_invalid_text):
        with pytest.raises(ValueError, match="Got more than one text prediction. This should not happen"):
            parse_inference_response(mock_invalid_predictions_invalid_text)
