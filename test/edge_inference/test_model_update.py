import os
import tempfile
from unittest import mock

from app.core.edge_inference import EdgeInferenceManager, delete_model_version, save_model_to_repository, should_update
from app.core.utils import ModelInfoWithBinary, parse_model_info, prefixed_ksuid


def test_save_model_with_binary_to_repository():
    test_predictor_metadata = """{"text_query":"there is a dog","mode":"BINARY"}"""
    with tempfile.TemporaryDirectory() as temp_dir:
        detector_id = "test_detector"
        ksuid_1 = prefixed_ksuid("test_")
        model_info = {
            "pipeline_config": "test_pipeline_config",
            "predictor_metadata": test_predictor_metadata,
            "model_binary_id": ksuid_1,
            "model_binary_url": "test_model_binary_url",
        }
        model_info = parse_model_info(model_info)
        save_model_to_repository(
            detector_id=detector_id,
            model_buffer=b"test_model1",
            model_info=model_info,
            repository_root=temp_dir,
        )

        # Check dir strucuture
        assert os.path.exists(os.path.join(temp_dir, detector_id))
        assert os.path.exists(os.path.join(temp_dir, detector_id, "1"))
        assert os.path.exists(os.path.join(temp_dir, detector_id, "1", "model.buf"))
        assert os.path.exists(os.path.join(temp_dir, detector_id, "1", "pipeline_config.yaml"))
        assert os.path.exists(os.path.join(temp_dir, detector_id, "1", "predictor_metadata.json"))
        id_file = os.path.join(temp_dir, detector_id, "1", "model_id.txt")
        assert os.path.exists(id_file)

        # Check contents of pipeline_config.yaml
        pipeline_config_file = os.path.join(temp_dir, detector_id, "1", "pipeline_config.yaml")
        with open(pipeline_config_file, "r") as f:
            assert f.read() == "test_pipeline_config\n...\n"  # three dots are added by yaml.dump

        # Check that the id file contains the correct ksuid
        with open(id_file, "r") as f:
            assert ksuid_1 == f.read()

        ksuid_2 = prefixed_ksuid("test_")
        model_info = {
            "pipeline_config": "test_pipeline_config_2",
            "predictor_metadata": test_predictor_metadata,
            "model_binary_id": ksuid_2,
            "model_binary_url": "test_model_binary_url_2",
        }
        model_info = parse_model_info(model_info)
        assert should_update(model_info, os.path.join(temp_dir, detector_id), 1)
        save_model_to_repository(
            detector_id=detector_id,
            model_buffer=b"test_model2",
            model_info=model_info,
            repository_root=temp_dir,
        )

        assert os.path.exists(os.path.join(temp_dir, detector_id, "2"))
        assert os.path.exists(os.path.join(temp_dir, detector_id, "2", "model.buf"))
        assert os.path.exists(os.path.join(temp_dir, detector_id, "2", "pipeline_config.yaml"))
        assert os.path.exists(os.path.join(temp_dir, detector_id, "2", "predictor_metadata.json"))
        id_file = os.path.join(temp_dir, detector_id, "2", "model_id.txt")
        assert os.path.exists(id_file)

        # Check contents of pipeline_config.yaml
        pipeline_config_file = os.path.join(temp_dir, detector_id, "2", "pipeline_config.yaml")
        with open(pipeline_config_file, "r") as f:
            assert f.read() == "test_pipeline_config_2\n...\n"  # three dots are added by yaml.dump

        with open(id_file, "r") as f:
            assert ksuid_2 == f.read()

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
            "model_binary_id": None,
            "model_binary_url": None,
        }
        model_info = parse_model_info(model_info)
        save_model_to_repository(
            detector_id=detector_id,
            model_buffer=None,
            model_info=model_info,
            repository_root=temp_dir,
        )

        # Check dir strucuture
        assert os.path.exists(os.path.join(temp_dir, detector_id))
        assert os.path.exists(os.path.join(temp_dir, detector_id, "1"))
        assert not os.path.exists(os.path.join(temp_dir, detector_id, "1", "model.buf"))
        assert os.path.exists(os.path.join(temp_dir, detector_id, "1", "pipeline_config.yaml"))
        assert os.path.exists(os.path.join(temp_dir, detector_id, "1", "predictor_metadata.json"))
        assert not os.path.exists(os.path.join(temp_dir, detector_id, "1", "model_id.txt"))

        # Check contents of pipeline_config.yaml
        pipeline_config_file = os.path.join(temp_dir, detector_id, "1", "pipeline_config.yaml")
        with open(pipeline_config_file, "r") as f:
            assert f.read() == "test_pipeline_config\n...\n"  # three dots are added by yaml.dump

        # A new version should be saved when the pipeline_config changes
        model_info = {
            "pipeline_config": "test_pipeline_config_2",
            "predictor_metadata": test_predictor_metadata,
            "model_binary_id": None,
            "model_binary_url": None,
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

        assert os.path.exists(os.path.join(temp_dir, detector_id, "2"))
        assert not os.path.exists(os.path.join(temp_dir, detector_id, "2", "model.buf"))
        assert os.path.exists(os.path.join(temp_dir, detector_id, "2", "pipeline_config.yaml"))
        assert os.path.exists(os.path.join(temp_dir, detector_id, "2", "predictor_metadata.json"))
        assert not os.path.exists(os.path.join(temp_dir, detector_id, "2", "model_id.txt"))

        # Check contents of pipeline_config.yaml
        pipeline_config_file = os.path.join(temp_dir, detector_id, "2", "pipeline_config.yaml")
        with open(pipeline_config_file, "r") as f:
            assert f.read() == "test_pipeline_config_2\n...\n"  # three dots are added by yaml.dump

        # A new version should not be saved when the pipeline config is the same
        model_info = {
            "pipeline_config": "test_pipeline_config_2",
            "predictor_metadata": test_predictor_metadata,
            "model_binary_id": None,
            "model_binary_url": None,
        }
        model_info = parse_model_info(model_info)
        assert not should_update(model_info, detector_dir, 2)


def test_update_model_with_no_new_model_available():
    test_predictor_metadata = """{"text_query":"there is a dog","mode":"BINARY"}"""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Setup a basic model repository
        test_ksuid = prefixed_ksuid("test_")
        model_info = {
            "pipeline_config": "test_pipeline_config",
            "predictor_metadata": test_predictor_metadata,
            "model_binary_id": test_ksuid,
            "model_binary_url": "test_model_binary_url",
        }
        model_info = ModelInfoWithBinary(**model_info)
        save_model_to_repository(
            detector_id="test_detector",
            model_buffer=b"test_model1",
            model_info=model_info,
            repository_root=temp_dir,
        )

        with mock.patch("app.core.edge_inference.fetch_model_info") as mock_fetch:
            with mock.patch("app.core.edge_inference.get_object_using_presigned_url") as mock_get_from_s3:
                mock_fetch.return_value = parse_model_info({
                    "model_binary_id": test_ksuid,
                    "predictor_metadata": test_predictor_metadata,
                    "pipeline_config": "test_pipeline_config",
                })
                edge_manager = EdgeInferenceManager(inference_configs=None, edge_config=None)
                edge_manager.MODEL_REPOSITORY = temp_dir  # type: ignore
                edge_manager.update_model("test_detector")
                # We shouldnt be pulling a model from s3 if we know there is nothing new available
                mock_get_from_s3.assert_not_called()
