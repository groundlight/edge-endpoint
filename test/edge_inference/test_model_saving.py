import os
import tempfile
from test.edge_inference.test_edge_inference_manager import validate_model_directory

from app.core.edge_inference import delete_model_version, save_model_to_repository, should_update
from app.core.utils import parse_model_info


def test_save_model_with_binary_to_repository():
    test_predictor_metadata = """{"text_query":"there is a dog","mode":"BINARY"}"""
    with tempfile.TemporaryDirectory() as temp_dir:
        detector_id = "test_detector"
        model_info = {
            "pipeline_config": "test_pipeline_config",
            "predictor_metadata": test_predictor_metadata,
            "trained_binary_id": "test_binary_id",
            "trained_binary_url": "test_binary_url",
        }
        model_info = parse_model_info(model_info)
        save_model_to_repository(
            detector_id=detector_id,
            model_buffer=b"test_model1",
            model_info=model_info,
            repository_root=temp_dir,
        )

        # Validate directory structure and contents
        validate_model_directory(temp_dir, detector_id, 1, model_info)

        model_info = {
            "pipeline_config": "test_pipeline_config_2",
            "predictor_metadata": test_predictor_metadata,
            "trained_binary_id": "test_binary_id_2",
            "trained_binary_url": "test_binary_url_2",
        }
        model_info = parse_model_info(model_info)
        assert should_update(model_info, os.path.join(temp_dir, detector_id), 1)
        save_model_to_repository(
            detector_id=detector_id,
            model_buffer=b"test_model2",
            model_info=model_info,
            repository_root=temp_dir,
        )

        # Validate directory structure and contents
        validate_model_directory(temp_dir, detector_id, 2, model_info)

        # Also test deleting a model version
        delete_model_version(detector_id, model_version=1, repository_root=temp_dir)
        assert not os.path.exists(os.path.join(temp_dir, detector_id, "1", "model.buf"))
        assert not os.path.exists(os.path.join(temp_dir, detector_id, "1", "pipeline_config.yaml"))
        assert not os.path.exists(os.path.join(temp_dir, detector_id, "1", "predictor_metadata.json"))
        assert not os.path.exists(os.path.join(temp_dir, detector_id, "1", "model_id.txt"))
        assert not os.path.exists(os.path.join(temp_dir, detector_id, "1"))


def test_save_model_with_no_binary_to_repository():
    test_predictor_metadata = """{"text_query":"there is a dog","mode":"BINARY"}"""
    with tempfile.TemporaryDirectory() as temp_dir:
        detector_id = "test_detector"
        model_info = {
            "pipeline_config": "test_pipeline_config",
            "predictor_metadata": test_predictor_metadata,
            "trained_binary_id": None,
            "trained_binary_url": None,
        }
        model_info = parse_model_info(model_info)
        save_model_to_repository(
            detector_id=detector_id,
            model_buffer=None,
            model_info=model_info,
            repository_root=temp_dir,
        )

        # Validate directory structure and contents
        validate_model_directory(temp_dir, detector_id, 1, model_info)

        # A new version should be saved when the pipeline_config changes
        model_info = {
            "pipeline_config": "test_pipeline_config_2",
            "predictor_metadata": test_predictor_metadata,
            "trained_binary_id": None,
            "trained_binary_url": None,
        }
        model_info = parse_model_info(model_info)
        detector_dir = os.path.join(temp_dir, detector_id)
        assert should_update(model_info, detector_dir, 1)
        save_model_to_repository(
            detector_id=detector_id,
            model_buffer=None,
            model_info=model_info,
            repository_root=temp_dir,
        )

        validate_model_directory(temp_dir, detector_id, 2, model_info)

        # A new version should not be saved when the pipeline config is the same
        model_info = {
            "pipeline_config": "test_pipeline_config_2",
            "predictor_metadata": test_predictor_metadata,
            "trained_binary_id": None,
            "trained_binary_url": None,
        }
        model_info = parse_model_info(model_info)
        assert not should_update(model_info, detector_dir, 2)
