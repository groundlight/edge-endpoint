import os
import tempfile
from unittest import mock

from app.core.edge_inference import EdgeInferenceManager, delete_model_version, save_model_to_repository


def test_save_model_to_repository():
    with tempfile.TemporaryDirectory() as temp_dir:
        save_model_to_repository(
            detector_id="test_detector",
            model_buffer=b"test_model1",
            pipeline_config="test_pipeline_config",
            binary_ksuid="ksu_1",
            repository_root=temp_dir,
        )

        # Check dir strucuture
        assert os.path.exists(os.path.join(temp_dir, "test_detector"))
        assert os.path.exists(os.path.join(temp_dir, "test_detector", "config.pbtxt"))
        assert os.path.exists(os.path.join(temp_dir, "test_detector", "binary_labels.txt"))
        assert os.path.exists(os.path.join(temp_dir, "test_detector", "1"))
        assert os.path.exists(os.path.join(temp_dir, "test_detector", "1", "model.buf"))
        assert os.path.exists(os.path.join(temp_dir, "test_detector", "1", "model.py"))
        id_file = os.path.join(temp_dir, "test_detector", "1", "model_id.txt")
        assert os.path.exists(id_file)

        with open(id_file, "r") as f:
            assert "ksu_1" == f.read()

        save_model_to_repository(
            detector_id="test_detector",
            model_buffer=b"test_model2",
            pipeline_config="test_pipeline_config",
            binary_ksuid="ksu_2",
            repository_root=temp_dir,
        )

        assert os.path.exists(os.path.join(temp_dir, "test_detector", "2"))
        assert os.path.exists(os.path.join(temp_dir, "test_detector", "2", "model.buf"))
        assert os.path.exists(os.path.join(temp_dir, "test_detector", "2", "model.py"))
        id_file = os.path.join(temp_dir, "test_detector", "2", "model_id.txt")
        assert os.path.exists(id_file)

        with open(id_file, "r") as f:
            assert "ksu_1" == f.read()

        delete_model_version("test_detector", "1")
        assert not os.path.exists(os.path.join(temp_dir, "test_detector", "1"))
        assert not os.path.exists(os.path.join(temp_dir, "test_detector", "1", "model.buf"))
        assert not os.path.exists(os.path.join(temp_dir, "test_detector", "1", "model.py"))
        assert not os.path.exists(os.path.join(temp_dir, "test_detector", "1", "model_id.txt"))


def test_update_model_with_no_new_model_available():
    with tempfile.TemporaryDirectory() as temp_dir:
        save_model_to_repository(
            detector_id="test_detector",
            model_buffer=b"test_model1",
            pipeline_config="test_pipeline_config",
            binary_ksuid="ksu_1",
            repository_root=temp_dir,
        )

        with mock.patch("app.core.edge_inference.fetch_model_urls") as mock_fetch:
            with mock.patch("app.core.edge_inference.get_object_using_presigned_url") as mock_get_from_s3:
                mock_fetch.return_value = {
                    "model_binary_id": "ksu_1",
                }
                edge_manager = EdgeInferenceManager(config=None)
                edge_manager.update_model("test_detector")  # Should return quickly because no new ksuid
                mock_get_from_s3.assert_not_called()
