import os
import tempfile
from test.edge_inference.test_edge_inference_manager import validate_model_directory

from app.core.edge_inference import (
    delete_model_version,
    delete_old_model_versions,
    save_models_to_repository,
    should_update,
)
from app.core.utils import parse_model_info


def test_save_model_with_binary_to_repository():
    test_predictor_metadata = """{"text_query":"there is a dog","mode":"BINARY"}"""
    with tempfile.TemporaryDirectory() as temp_dir:
        detector_id = "test_detector"
        model_info = {
            "pipeline_config": "test_pipeline_config",
            "predictor_metadata": test_predictor_metadata,
            "model_binary_id": "test_binary_id",
            "model_binary_url": "test_binary_url",
            "oodd_pipeline_config": "test_oodd_pipeline_config",
            "oodd_model_binary_id": "test_oodd_binary_id",
            "oodd_model_binary_url": "test_oodd_binary_url",
        }
        edge_model_info, oodd_model_info = parse_model_info(model_info)
        save_models_to_repository(
            detector_id=detector_id,
            edge_model_buffer=b"test_model1",
            edge_model_info=edge_model_info,
            oodd_model_buffer=b"test_oodd_model1",
            oodd_model_info=oodd_model_info,
            repository_root=temp_dir,
        )

        # Validate directory structure and contents
        validate_model_directory(temp_dir, detector_id, 1, edge_model_info)
        validate_model_directory(temp_dir, detector_id, 1, oodd_model_info, is_oodd=True)

        model_info = {
            "pipeline_config": "test_pipeline_config_2",
            "predictor_metadata": test_predictor_metadata,
            "model_binary_id": "test_binary_id_2",
            "model_binary_url": "test_binary_url_2",
            "oodd_pipeline_config": "test_oodd_pipeline_config_2",
            "oodd_model_binary_id": "test_oodd_binary_id_2",
            "oodd_model_binary_url": "test_oodd_binary_url_2",
        }
        edge_model_info, oodd_model_info = parse_model_info(model_info)
        assert should_update(edge_model_info, os.path.join(temp_dir, detector_id), 1)
        assert should_update(oodd_model_info, os.path.join(temp_dir, detector_id), 1)
        save_models_to_repository(
            detector_id=detector_id,
            edge_model_buffer=b"test_model2",
            edge_model_info=edge_model_info,
            oodd_model_buffer=b"test_oodd_model2",
            oodd_model_info=oodd_model_info,
            repository_root=temp_dir,
        )

        # Validate directory structure and contents
        validate_model_directory(temp_dir, detector_id, 2, edge_model_info)
        validate_model_directory(temp_dir, detector_id, 2, oodd_model_info, is_oodd=True)

        # Also test deleting a model version
        delete_model_version(model_dir=os.path.join(temp_dir, detector_id, "primary"), model_version=1)
        assert not os.path.exists(os.path.join(temp_dir, detector_id, "primary", "1", "model.buf"))
        assert not os.path.exists(os.path.join(temp_dir, detector_id, "primary", "1", "pipeline_config.yaml"))
        assert not os.path.exists(os.path.join(temp_dir, detector_id, "primary", "1", "predictor_metadata.json"))
        assert not os.path.exists(os.path.join(temp_dir, detector_id, "primary", "1", "model_id.txt"))
        assert not os.path.exists(os.path.join(temp_dir, detector_id, "primary", "1"))


def test_save_model_with_no_binary_to_repository():
    test_predictor_metadata = """{"text_query":"there is a dog","mode":"BINARY"}"""
    with tempfile.TemporaryDirectory() as temp_dir:
        detector_id = "test_detector"
        model_info = {
            "pipeline_config": "test_pipeline_config",
            "predictor_metadata": test_predictor_metadata,
            "model_binary_id": None,
            "model_binary_url": None,
            "oodd_pipeline_config": "test_oodd_pipeline_config",
            "oodd_model_binary_id": None,
            "oodd_model_binary_url": None,
        }
        edge_model_info, oodd_model_info = parse_model_info(model_info)
        save_models_to_repository(
            detector_id=detector_id,
            edge_model_buffer=None,
            edge_model_info=edge_model_info,
            oodd_model_buffer=None,
            oodd_model_info=oodd_model_info,
            repository_root=temp_dir,
        )

        # Validate directory structure and contents
        validate_model_directory(temp_dir, detector_id, 1, edge_model_info)
        validate_model_directory(temp_dir, detector_id, 1, oodd_model_info, is_oodd=True)

        # A new version should be saved when the pipeline_config changes
        model_info = {
            "pipeline_config": "test_pipeline_config_2",
            "predictor_metadata": test_predictor_metadata,
            "model_binary_id": None,
            "model_binary_url": None,
            "oodd_pipeline_config": "test_oodd_pipeline_config_2",
            "oodd_model_binary_id": None,
            "oodd_model_binary_url": None,
        }
        edge_model_info, oodd_model_info = parse_model_info(model_info)
        assert should_update(edge_model_info, os.path.join(temp_dir, detector_id, "primary"), 1)
        assert should_update(oodd_model_info, os.path.join(temp_dir, detector_id, "oodd"), 1)
        save_models_to_repository(
            detector_id=detector_id,
            edge_model_buffer=None,
            edge_model_info=edge_model_info,
            oodd_model_buffer=None,
            oodd_model_info=oodd_model_info,
            repository_root=temp_dir,
        )

        validate_model_directory(temp_dir, detector_id, 2, edge_model_info)
        validate_model_directory(temp_dir, detector_id, 2, oodd_model_info, is_oodd=True)

        # A new version should not be saved when the pipeline config is the same
        model_info = {
            "pipeline_config": "test_pipeline_config_2",
            "predictor_metadata": test_predictor_metadata,
            "model_binary_id": None,
            "model_binary_url": None,
            "oodd_pipeline_config": "test_oodd_pipeline_config_2",
            "oodd_model_binary_id": None,
            "oodd_model_binary_url": None,
        }
        edge_model_info, oodd_model_info = parse_model_info(model_info)
        assert not should_update(edge_model_info, os.path.join(temp_dir, detector_id, "primary"), 2)
        assert not should_update(oodd_model_info, os.path.join(temp_dir, detector_id, "oodd"), 2)


def test_delete_old_model_versions():
    with tempfile.TemporaryDirectory() as temp_dir:
        detector_id = "test_detector"
        primary_model_dir = os.path.join(temp_dir, detector_id, "primary")
        oodd_model_dir = os.path.join(temp_dir, detector_id, "oodd")

        # Save 3 mock model version folders to set up
        os.makedirs(os.path.join(primary_model_dir, "1"))
        os.makedirs(os.path.join(primary_model_dir, "2"))
        os.makedirs(os.path.join(primary_model_dir, "3"))
        os.makedirs(os.path.join(oodd_model_dir, "1"))
        os.makedirs(os.path.join(oodd_model_dir, "2"))
        os.makedirs(os.path.join(oodd_model_dir, "3"))

        # Keep 2 latest model versions, delete the first one
        delete_old_model_versions(detector_id=detector_id, repository_root=temp_dir, num_to_keep=2)

        # Version 1 for both primary and oodd should be deleted
        assert not os.path.exists(os.path.join(primary_model_dir, "1"))
        assert not os.path.exists(os.path.join(oodd_model_dir, "1"))

        # Versions 2 and 3 for both primary and oodd should be kept
        assert os.path.exists(os.path.join(primary_model_dir, "2"))
        assert os.path.exists(os.path.join(oodd_model_dir, "2"))
        assert os.path.exists(os.path.join(primary_model_dir, "3"))
        assert os.path.exists(os.path.join(oodd_model_dir, "3"))

        # Update the primary model to version 4 but not the oodd model
        os.makedirs(os.path.join(primary_model_dir, "4"))

        delete_old_model_versions(detector_id=detector_id, repository_root=temp_dir, num_to_keep=2)

        # Version 2 for primary should be deleted, but version 2 for oodd should be kept
        assert not os.path.exists(os.path.join(primary_model_dir, "2"))
        assert os.path.exists(os.path.join(oodd_model_dir, "2"))

        # Update the oodd model but not the primary model
        os.makedirs(os.path.join(oodd_model_dir, "4"))

        delete_old_model_versions(detector_id=detector_id, repository_root=temp_dir, num_to_keep=2)

        # Version 2 should now be deleted for both primary and oodd
        assert not os.path.exists(os.path.join(primary_model_dir, "2"))
        assert not os.path.exists(os.path.join(oodd_model_dir, "2"))

        # and both primary and oodd should have versions 3 and 4
        assert os.path.exists(os.path.join(primary_model_dir, "3"))
        assert os.path.exists(os.path.join(oodd_model_dir, "3"))
        assert os.path.exists(os.path.join(primary_model_dir, "4"))
        assert os.path.exists(os.path.join(oodd_model_dir, "4"))


def test_switch_to_new_model_repository_format():
    with tempfile.TemporaryDirectory() as temp_dir:
        detector_id = "test_detector"
        test_predictor_metadata = """{"text_query":"there is a dog","mode":"BINARY"}"""
        primary_model_dir = os.path.join(temp_dir, detector_id, "primary")
        oodd_model_dir = os.path.join(temp_dir, detector_id, "oodd")

        old_model_dir = os.path.join(temp_dir, detector_id)
        os.makedirs(old_model_dir)

        # Old model repository format had versions stored in the detector directory
        os.makedirs(os.path.join(old_model_dir, "4"))
        os.makedirs(os.path.join(old_model_dir, "5"))

        # Save a new model version
        model_info = {
            "pipeline_config": "test_pipeline_config",
            "predictor_metadata": test_predictor_metadata,
            "model_binary_id": "test_binary_id",
            "model_binary_url": "test_binary_url",
            "oodd_pipeline_config": "test_oodd_pipeline_config",
            "oodd_model_binary_id": "test_oodd_binary_id",
            "oodd_model_binary_url": "test_oodd_binary_url",
        }
        edge_model_info, oodd_model_info = parse_model_info(model_info)
        save_models_to_repository(
            detector_id=detector_id,
            edge_model_buffer=b"test_model1",
            edge_model_info=edge_model_info,
            oodd_model_buffer=b"test_oodd_model1",
            oodd_model_info=oodd_model_info,
            repository_root=temp_dir,
        )

        # Saving a new version creates the new model repository format, with new versions
        assert os.path.exists(primary_model_dir)
        assert os.path.exists(oodd_model_dir)
        assert os.path.exists(os.path.join(primary_model_dir, "1"))
        assert os.path.exists(os.path.join(primary_model_dir, "1", "model.buf"))
        assert os.path.exists(os.path.join(primary_model_dir, "1", "pipeline_config.yaml"))
        assert os.path.exists(os.path.join(primary_model_dir, "1", "predictor_metadata.json"))
        assert os.path.exists(os.path.join(primary_model_dir, "1", "model_id.txt"))
        assert os.path.exists(os.path.join(oodd_model_dir, "1"))
        assert os.path.exists(os.path.join(oodd_model_dir, "1", "model.buf"))
        assert os.path.exists(os.path.join(oodd_model_dir, "1", "pipeline_config.yaml"))
        assert os.path.exists(os.path.join(oodd_model_dir, "1", "predictor_metadata.json"))
        assert os.path.exists(os.path.join(oodd_model_dir, "1", "model_id.txt"))

        # Old model repository versions persist through initial saving
        assert os.path.exists(os.path.join(old_model_dir, "4"))
        assert os.path.exists(os.path.join(old_model_dir, "5"))

        # When we delete old model versions, all versions from the old model repository format are deleted
        delete_old_model_versions(detector_id=detector_id, repository_root=temp_dir, num_to_keep=2)
        assert not os.path.exists(os.path.join(old_model_dir, "4"))
        assert not os.path.exists(os.path.join(old_model_dir, "5"))

        # And the new models persist
        assert os.path.exists(os.path.join(primary_model_dir, "1"))
        assert os.path.exists(os.path.join(oodd_model_dir, "1"))
