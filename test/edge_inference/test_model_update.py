import os
import tempfile
from unittest import mock

from app.core.edge_inference import EdgeInferenceManager, delete_model_version, save_model_to_repository
from app.core.utils import prefixed_ksuid


def test_save_model_to_repository():
    with tempfile.TemporaryDirectory() as temp_dir:
        detector_id = "test_detector"
        ksuid_1 = prefixed_ksuid("test_")
        save_model_to_repository(
            detector_id=detector_id,
            model_buffer=b"test_model1",
            pipeline_config="test_pipeline_config",
            binary_ksuid=ksuid_1,
            repository_root=temp_dir,
        )

        # Check dir strucuture
        assert os.path.exists(os.path.join(temp_dir, detector_id))
        assert os.path.exists(os.path.join(temp_dir, detector_id, "config.pbtxt"))
        assert os.path.exists(os.path.join(temp_dir, detector_id, "binary_labels.txt"))
        assert os.path.exists(os.path.join(temp_dir, detector_id, "1"))
        assert os.path.exists(os.path.join(temp_dir, detector_id, "1", "model.buf"))
        assert os.path.exists(os.path.join(temp_dir, detector_id, "1", "model.py"))
        id_file = os.path.join(temp_dir, detector_id, "1", "model_id.txt")
        assert os.path.exists(id_file)

        with open(id_file, "r") as f:
            assert ksuid_1 == f.read()

        ksuid_2 = prefixed_ksuid("test_")
        save_model_to_repository(
            detector_id=detector_id,
            model_buffer=b"test_model2",
            pipeline_config="test_pipeline_config",
            binary_ksuid=ksuid_2,
            repository_root=temp_dir,
        )

        assert os.path.exists(os.path.join(temp_dir, detector_id, "2"))
        assert os.path.exists(os.path.join(temp_dir, detector_id, "2", "model.buf"))
        assert os.path.exists(os.path.join(temp_dir, detector_id, "2", "model.py"))
        id_file = os.path.join(temp_dir, detector_id, "2", "model_id.txt")
        assert os.path.exists(id_file)

        with open(id_file, "r") as f:
            assert ksuid_2 == f.read()

        # Also test deleting a model version
        delete_model_version(detector_id, model_version=1, repository_root=temp_dir)
        assert not os.path.exists(os.path.join(temp_dir, detector_id, "1", "model.buf"))
        assert not os.path.exists(os.path.join(temp_dir, detector_id, "1", "model.py"))
        assert not os.path.exists(os.path.join(temp_dir, detector_id, "1", "model_id.txt"))
        assert not os.path.exists(os.path.join(temp_dir, detector_id, "1"))


def test_update_model_with_no_new_model_available():
    with tempfile.TemporaryDirectory() as temp_dir:
        # Setup a basic model repository
        test_ksuid = prefixed_ksuid("test_")
        save_model_to_repository(
            detector_id="test_detector",
            model_buffer=b"test_model1",
            pipeline_config="test_pipeline_config",
            binary_ksuid=test_ksuid,
            repository_root=temp_dir,
        )

        with mock.patch("app.core.edge_inference.fetch_model_urls") as mock_fetch:
            with mock.patch("app.core.edge_inference.get_object_using_presigned_url") as mock_get_from_s3:
                mock_fetch.return_value = {
                    "model_binary_id": test_ksuid,
                }
                edge_manager = EdgeInferenceManager(config=None)
                edge_manager.MODEL_REPOSITORY = temp_dir
                edge_manager.update_model("test_detector")
                # We shouldnt be pulling a model from s3 if we know there is nothing new available
                mock_get_from_s3.assert_not_called()
