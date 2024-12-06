import os
import tempfile
from unittest import mock

import pytest

from app.core.edge_inference import EdgeInferenceManager
from app.core.utils import ModelInfoBase, ModelInfoNoBinary, ModelInfoWithBinary


def validate_model_directory(base_dir: str, detector_id: str, version: int, model_info: ModelInfoBase):
    """Helper function to validate the structure and contents of a model directory."""
    version_str = str(version)
    model_dir = os.path.join(base_dir, detector_id, version_str)

    # Validate structure and always-present files
    assert os.path.exists(os.path.join(base_dir, detector_id))
    assert os.path.exists(model_dir)
    assert os.path.exists(os.path.join(model_dir, "pipeline_config.yaml"))
    assert os.path.exists(os.path.join(model_dir, "predictor_metadata.json"))

    # Validate pipeline_config.yaml contents
    pipeline_config_file = os.path.join(model_dir, "pipeline_config.yaml")
    with open(pipeline_config_file, "r") as f:
        assert f.read() == model_info.pipeline_config + "\n...\n"  # YAML adds three dots by default

    # Validate files for when a model binary is present
    if isinstance(model_info, ModelInfoWithBinary):
        assert os.path.exists(os.path.join(model_dir, "model.buf"))

        id_file = os.path.join(model_dir, "model_id.txt")
        assert os.path.exists(id_file)
        with open(id_file, "r") as f:
            assert model_info.model_binary_id == f.read()


@pytest.fixture
def model_info_with_binary() -> ModelInfoWithBinary:
    test_predictor_metadata = """{"text_query":"there is a dog","mode":"BINARY"}"""
    model_info = {
        "pipeline_config": "test_pipeline_config",
        "predictor_metadata": test_predictor_metadata,
        "model_binary_id": "test_binary_id",
        "model_binary_url": "test_model_binary_url",
    }
    return ModelInfoWithBinary(**model_info)


@pytest.fixture
def model_info_no_binary() -> ModelInfoNoBinary:
    test_predictor_metadata = """{"text_query":"there is a dog","mode":"BINARY"}"""
    model_info = {
        "pipeline_config": "test_pipeline_config",
        "predictor_metadata": test_predictor_metadata,
        "model_binary_id": None,
        "model_binary_url": None,
    }
    return ModelInfoNoBinary(**model_info)


class TestEdgeInferenceMangager:
    def test_update_model_with_binary(self, model_info_with_binary):
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch("app.core.edge_inference.fetch_model_info") as mock_fetch:
                with mock.patch("app.core.edge_inference.get_object_using_presigned_url") as mock_get_from_s3:
                    mock_get_from_s3.return_value = b"test_model"
                    mock_fetch.return_value = model_info_with_binary
                    edge_manager = EdgeInferenceManager(detector_inference_configs=None)
                    edge_manager.MODEL_REPOSITORY = temp_dir  # type: ignore
                    detector_id = "test_detector"
                    edge_manager.update_model(detector_id)

                    validate_model_directory(temp_dir, detector_id, 1, model_info_with_binary)

                    # Should create a new version for new model info
                    mock_get_from_s3.return_value = b"test_model_2"
                    model_info_with_binary_2 = model_info_with_binary
                    model_info_with_binary_2.model_binary_id = "test_binary_id_2"
                    model_info_with_binary_2.model_binary_url = "test_model_binary_url_2"
                    mock_fetch.return_value = model_info_with_binary_2
                    edge_manager.update_model(detector_id)

                    validate_model_directory(temp_dir, detector_id, 2, model_info_with_binary_2)

                with mock.patch("app.core.edge_inference.get_object_using_presigned_url") as mock_get_from_s3:
                    edge_manager.update_model(detector_id)
                    # Shouldn't pull a model from s3 if there is no new binary available
                    mock_get_from_s3.assert_not_called()
                    # Should not create a new version for the same model info
                    assert not os.path.exists(os.path.join(temp_dir, detector_id, "3"))

    def test_update_model_no_binary(self, model_info_no_binary):
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch("app.core.edge_inference.fetch_model_info") as mock_fetch:
                mock_fetch.return_value = model_info_no_binary
                edge_manager = EdgeInferenceManager(detector_inference_configs=None)
                edge_manager.MODEL_REPOSITORY = temp_dir  # type: ignore
                detector_id = "test_detector"
                edge_manager.update_model(detector_id)

                validate_model_directory(temp_dir, detector_id, 1, model_info_no_binary)

                # Should create a new version for new pipeline config
                model_info_no_binary_2 = model_info_no_binary
                model_info_no_binary_2.pipeline_config = "test_pipeline_config_2"
                mock_fetch.return_value = model_info_no_binary_2
                edge_manager.update_model(detector_id)

                validate_model_directory(temp_dir, detector_id, 2, model_info_no_binary_2)

                edge_manager.update_model(detector_id)
                # Should not create a new version for the same pipeline config
                assert not os.path.exists(os.path.join(temp_dir, detector_id, "3"))
