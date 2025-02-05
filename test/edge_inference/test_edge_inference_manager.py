import os
import tempfile
from unittest import mock

import pytest

from app.core.edge_inference import EdgeInferenceManager
from app.core.utils import ModelInfoBase, ModelInfoNoBinary, ModelInfoWithBinary


def validate_model_directory(base_dir: str, detector_id: str, version: int, model_info: ModelInfoBase, is_oodd: bool = False):
    """Helper function to validate the structure and contents of a model directory."""
    version_str = str(version)
    model_dir = os.path.join(base_dir, detector_id + ("_oodd" if is_oodd else ""), version_str)

    # Validate structure and always-present files
    assert os.path.exists(os.path.join(base_dir, detector_id + ("_oodd" if is_oodd else ""))), f"Model directory {os.path.join(base_dir, detector_id + ('_oodd' if is_oodd else ''))} does not exist"
    assert os.path.exists(model_dir), f"Model directory {model_dir} does not exist"
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
def edge_model_info_with_binary() -> ModelInfoWithBinary:
    test_predictor_metadata = """{"text_query":"there is a dog","mode":"BINARY"}"""
    model_info = {
        "pipeline_config": "test_pipeline_config",
        "predictor_metadata": test_predictor_metadata,
        "model_binary_id": "test_binary_id",
        "model_binary_url": "test_model_binary_url",
        "oodd_pipeline_config": "test_oodd_pipeline_config",
        "oodd_model_binary_id": "test_oodd_binary_id",
        "oodd_model_binary_url": "test_oodd_model_binary_url",
    }
    return ModelInfoWithBinary(**model_info)


@pytest.fixture
def oodd_model_info_with_binary() -> ModelInfoWithBinary:
    test_predictor_metadata = """{"text_query":"there is a dog","mode":"BINARY"}"""
    model_info = {
        "oodd_pipeline_config": "test_oodd_pipeline_config",
        "predictor_metadata": test_predictor_metadata,
        "oodd_model_binary_id": "test_oodd_binary_id",
        "oodd_model_binary_url": "test_oodd_model_binary_url",
    }
    return ModelInfoWithBinary(
        pipeline_config=model_info["oodd_pipeline_config"],
        predictor_metadata=model_info["predictor_metadata"],
        model_binary_id=model_info["oodd_model_binary_id"],
        model_binary_url=model_info["oodd_model_binary_url"],
    )


@pytest.fixture
def edge_model_info_no_binary() -> ModelInfoNoBinary:
    test_predictor_metadata = """{"text_query":"there is a dog","mode":"BINARY"}"""
    model_info = {
        "pipeline_config": "test_pipeline_config",
        "predictor_metadata": test_predictor_metadata,
        "model_binary_id": None,
        "model_binary_url": None,
        "oodd_pipeline_config": "test_oodd_pipeline_config",
    }
    return ModelInfoNoBinary(**model_info)


@pytest.fixture
def oodd_model_info_no_binary() -> ModelInfoNoBinary:
    test_predictor_metadata = """{"text_query":"there is a dog","mode":"BINARY"}"""
    model_info = {
        "oodd_pipeline_config": "test_oodd_pipeline_config",
        "predictor_metadata": test_predictor_metadata,
    }
    return ModelInfoNoBinary(
        pipeline_config=model_info["oodd_pipeline_config"],
        predictor_metadata=model_info["predictor_metadata"],
    )


class TestEdgeInferenceManager:
    def test_update_model_with_binary(self, edge_model_info_with_binary, oodd_model_info_with_binary):
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch("app.core.edge_inference.fetch_model_info") as mock_fetch:
                with mock.patch("app.core.edge_inference.get_object_using_presigned_url") as mock_get_from_s3:
                    mock_get_from_s3.return_value = b"test_model"
                    mock_fetch.return_value = (edge_model_info_with_binary, oodd_model_info_with_binary)
                    edge_manager = EdgeInferenceManager(detector_inference_configs=None)
                    edge_manager.MODEL_REPOSITORY = temp_dir  # type: ignore
                    detector_id = "test_detector"
                    edge_manager.update_models_if_available(detector_id)

                    validate_model_directory(temp_dir, detector_id, 1, edge_model_info_with_binary)
                    validate_model_directory(temp_dir, detector_id, 1, oodd_model_info_with_binary, is_oodd=True)

                    # Should create a new version for new model info
                    mock_get_from_s3.return_value = b"test_model_2"
                    edge_model_info_with_binary_2 = edge_model_info_with_binary
                    edge_model_info_with_binary_2.model_binary_id = "test_binary_id_2"
                    edge_model_info_with_binary_2.model_binary_url = "test_model_binary_url_2"
                    oodd_model_info_with_binary_2 = oodd_model_info_with_binary
                    oodd_model_info_with_binary_2.model_binary_id = "test_oodd_binary_id_2"
                    oodd_model_info_with_binary_2.model_binary_url = "test_oodd_model_binary_url_2"
                    mock_fetch.return_value = (edge_model_info_with_binary_2, oodd_model_info_with_binary_2)
                    edge_manager.update_models_if_available(detector_id)

                    validate_model_directory(temp_dir, detector_id, 2, edge_model_info_with_binary_2)
                    validate_model_directory(temp_dir, detector_id, 2, oodd_model_info_with_binary_2, is_oodd=True)

                with mock.patch("app.core.edge_inference.get_object_using_presigned_url") as mock_get_from_s3:
                    edge_manager.update_models_if_available(detector_id)
                    # Shouldn't pull a model from s3 if there is no new binary available
                    mock_get_from_s3.assert_not_called()
                    # Should not create a new version for the same model info
                    assert not os.path.exists(os.path.join(temp_dir, detector_id, "3"))
                    assert not os.path.exists(os.path.join(temp_dir, detector_id + "_oodd", "3"))

    def test_update_model_no_binary(self, edge_model_info_no_binary, oodd_model_info_no_binary):
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch("app.core.edge_inference.fetch_model_info") as mock_fetch:
                mock_fetch.return_value = (edge_model_info_no_binary, oodd_model_info_no_binary)
                edge_manager = EdgeInferenceManager(detector_inference_configs=None)
                edge_manager.MODEL_REPOSITORY = temp_dir  # type: ignore
                detector_id = "test_detector"
                edge_manager.update_models_if_available(detector_id)

                validate_model_directory(temp_dir, detector_id, 1, edge_model_info_no_binary)
                validate_model_directory(temp_dir, detector_id, 1, oodd_model_info_no_binary, is_oodd=True)

                # Should create a new version for new pipeline config
                edge_model_info_no_binary_2 = edge_model_info_no_binary
                edge_model_info_no_binary_2.pipeline_config = "test_pipeline_config_2"
                oodd_model_info_no_binary_2 = oodd_model_info_no_binary
                oodd_model_info_no_binary_2.pipeline_config = "test_oodd_pipeline_config_2"
                mock_fetch.return_value = (edge_model_info_no_binary_2, oodd_model_info_no_binary_2)
                edge_manager.update_models_if_available(detector_id)

                validate_model_directory(temp_dir, detector_id, 2, edge_model_info_no_binary_2)
                validate_model_directory(temp_dir, detector_id, 2, oodd_model_info_no_binary_2, is_oodd=True)

                edge_manager.update_models_if_available(detector_id)
                # Should not create a new version for the same pipeline config
                assert not os.path.exists(os.path.join(temp_dir, detector_id, "3"))
                assert not os.path.exists(os.path.join(temp_dir, detector_id + "_oodd", "3"))