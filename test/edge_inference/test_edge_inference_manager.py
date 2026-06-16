import os
import tempfile
from unittest import mock

import pytest
import yaml
from model import ModeEnum

from app.core.edge_inference import EdgeInferenceManager
from app.core.naming import get_edge_inference_service_name
from app.core.utils import ModelInfoBase, ModelInfoNoBinary, ModelInfoWithBinary


def _fake_db(minimal_compatible: bool = False):
    """Build a DatabaseManager stub that returns a record with the given minimal_compatible flag."""
    db = mock.Mock()
    record = mock.Mock()
    record.minimal_compatible = minimal_compatible
    db.get_inference_deployment_record.return_value = record
    return db


def validate_model_directory(
    model_repository: str, detector_id: str, version: int, model_info: ModelInfoBase, is_oodd: bool = False
):
    """Helper function to validate the structure and contents of a model directory."""
    version_str = str(version)
    model_dir = os.path.join(model_repository, detector_id, "oodd" if is_oodd else "primary", version_str)

    # Validate structure and always-present files
    assert os.path.exists(os.path.join(model_repository, detector_id))
    assert os.path.exists(model_dir)
    assert os.path.exists(os.path.join(model_dir, "pipeline_config.yaml"))
    assert os.path.exists(os.path.join(model_dir, "predictor_metadata.json"))

    # Validate pipeline_config.yaml contents
    pipeline_config_file = os.path.join(model_dir, "pipeline_config.yaml")
    with open(pipeline_config_file, "r") as f:
        file_content = f.read()
    assert yaml.safe_load(file_content) == yaml.safe_load(model_info.pipeline_config)

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
    @pytest.fixture(autouse=True)
    def clear_oodd_cache(self):
        import app.core.edge_inference as ei_mod

        ei_mod._separate_oodd_cache.clear()
        yield
        ei_mod._separate_oodd_cache.clear()

    def test_update_model_with_binary(self, edge_model_info_with_binary, oodd_model_info_with_binary):
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch("app.core.edge_inference.fetch_model_info") as mock_fetch:
                with mock.patch("app.core.edge_inference.get_object_using_presigned_url") as mock_get_from_s3:
                    mock_get_from_s3.return_value = b"test_model"
                    mock_fetch.return_value = (edge_model_info_with_binary, oodd_model_info_with_binary)
                    edge_manager = EdgeInferenceManager(db_manager=_fake_db())
                    edge_manager.MODEL_REPOSITORY = temp_dir  # type: ignore
                    detector_id = "test_detector"
                    edge_manager.sync_models_from_cloud(detector_id)

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
                    edge_manager.sync_models_from_cloud(detector_id)

                    validate_model_directory(temp_dir, detector_id, 2, edge_model_info_with_binary_2)
                    validate_model_directory(temp_dir, detector_id, 2, oodd_model_info_with_binary_2, is_oodd=True)

                with mock.patch("app.core.edge_inference.get_object_using_presigned_url") as mock_get_from_s3:
                    edge_manager.sync_models_from_cloud(detector_id)
                    # Shouldn't pull a model from s3 if there is no new binary available
                    mock_get_from_s3.assert_not_called()
                    # Should not create a new version for the same model info
                    assert not os.path.exists(os.path.join(temp_dir, detector_id, "primary", "3"))
                    assert not os.path.exists(os.path.join(temp_dir, detector_id, "oodd", "3"))

    def test_update_model_no_binary(self, edge_model_info_no_binary, oodd_model_info_no_binary):
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch("app.core.edge_inference.fetch_model_info") as mock_fetch:
                mock_fetch.return_value = (edge_model_info_no_binary, oodd_model_info_no_binary)
                edge_manager = EdgeInferenceManager(db_manager=_fake_db())
                edge_manager.MODEL_REPOSITORY = temp_dir  # type: ignore
                detector_id = "test_detector"
                edge_manager.sync_models_from_cloud(detector_id)

                validate_model_directory(temp_dir, detector_id, 1, edge_model_info_no_binary)
                validate_model_directory(temp_dir, detector_id, 1, oodd_model_info_no_binary, is_oodd=True)

                # Should create a new version for new pipeline config
                edge_model_info_no_binary_2 = edge_model_info_no_binary
                edge_model_info_no_binary_2.pipeline_config = "test_pipeline_config_2"
                oodd_model_info_no_binary_2 = oodd_model_info_no_binary
                oodd_model_info_no_binary_2.pipeline_config = "test_oodd_pipeline_config_2"
                mock_fetch.return_value = (edge_model_info_no_binary_2, oodd_model_info_no_binary_2)
                edge_manager.sync_models_from_cloud(detector_id)

                validate_model_directory(temp_dir, detector_id, 2, edge_model_info_no_binary_2)
                validate_model_directory(temp_dir, detector_id, 2, oodd_model_info_no_binary_2, is_oodd=True)

                edge_manager.sync_models_from_cloud(detector_id)
                # Should not create a new version for the same pipeline config
                assert not os.path.exists(os.path.join(temp_dir, detector_id, "primary", "3"))
                assert not os.path.exists(os.path.join(temp_dir, detector_id, "oodd", "3"))

    def test_run_inference_with_oodd(self):
        mock_response = {
            "multi_predictions": None,
            "predictions": {"confidences": [0.54], "labels": [0]},
            "secondary_predictions": None,
        }

        with mock.patch("app.core.edge_inference.submit_image_for_inference") as mock_submit:
            mock_submit.return_value = mock_response
            # separate_oodd_inference is True by default
            edge_manager = EdgeInferenceManager(db_manager=_fake_db())
            edge_manager.run_inference("test_detector", b"test_image", "image/jpeg", mode=ModeEnum.BINARY)
            primary_inference_client_url = get_edge_inference_service_name("test_detector") + ":8000"
            oodd_inference_client_url = get_edge_inference_service_name("test_detector", is_oodd=True) + ":8000"

            # Assert that run inference was called twice, once for primary and once for OODD
            assert mock_submit.call_count == 2
            calls = mock_submit.call_args_list
            primary_call = mock.call(primary_inference_client_url, b"test_image", "image/jpeg")
            oodd_call = mock.call(oodd_inference_client_url, b"test_image", "image/jpeg")

            assert primary_call in calls
            assert oodd_call in calls

    def test_run_inference_without_oodd(self):
        mock_response = {
            "multi_predictions": None,
            "predictions": {"confidences": [0.54], "labels": [0]},
            "secondary_predictions": None,
        }

        with (
            mock.patch("app.core.inference_image.INFERENCE_IMAGE_MODE", "minimal_if_compatible"),
            mock.patch("app.core.edge_inference.submit_image_for_inference") as mock_submit,
        ):
            mock_submit.return_value = mock_response
            edge_manager = EdgeInferenceManager(db_manager=_fake_db(minimal_compatible=True))
            edge_manager.run_inference("test_detector", b"test_image", "image/jpeg", mode=ModeEnum.BINARY)
            primary_inference_client_url = get_edge_inference_service_name("test_detector") + ":8000"

            # Assert that the mock_submit was called only once for primary inference, never for OODD
            assert mock_submit.call_count == 1
            mock_submit.assert_called_once_with(primary_inference_client_url, b"test_image", "image/jpeg")

    def _write_model_id(self, repository: str, detector_id: str, version: int, ksuid: str, is_oodd: bool = False):
        sub = "oodd" if is_oodd else "primary"
        version_dir = os.path.join(repository, detector_id, sub, str(version))
        os.makedirs(version_dir, exist_ok=True)
        with open(os.path.join(version_dir, "model_id.txt"), "w") as f:
            f.write(ksuid)

    def test_run_inference_stamps_mlb_keys(self):
        """With OODD enabled and model_id.txt present for both, output_dict carries both keys."""
        mock_response = {
            "multi_predictions": None,
            "predictions": {"confidences": [0.54], "labels": [0]},
            "secondary_predictions": None,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            detector_id = "test_detector"
            self._write_model_id(temp_dir, detector_id, 1, "prim_ksuid_abc")
            self._write_model_id(temp_dir, detector_id, 1, "oodd_ksuid_xyz", is_oodd=True)

            with mock.patch("app.core.edge_inference.submit_image_for_inference") as mock_submit:
                mock_submit.return_value = mock_response
                edge_manager = EdgeInferenceManager(db_manager=_fake_db())
                edge_manager.MODEL_REPOSITORY = temp_dir  # type: ignore
                output = edge_manager.run_inference(detector_id, b"test_image", "image/jpeg", mode=ModeEnum.BINARY)

                assert output["mlb_key"] == "prim_ksuid_abc"
                assert output["oodd_mlb_key"] == "oodd_ksuid_xyz"

    def test_run_inference_stamps_mlb_key_without_oodd(self):
        """With separate_oodd_inference=False, only mlb_key is stamped."""
        mock_response = {
            "multi_predictions": None,
            "predictions": {"confidences": [0.54], "labels": [0]},
            "secondary_predictions": None,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            detector_id = "test_detector"
            self._write_model_id(temp_dir, detector_id, 1, "prim_ksuid_only")

            with (
                mock.patch("app.core.inference_image.INFERENCE_IMAGE_MODE", "minimal_if_compatible"),
                mock.patch("app.core.edge_inference.submit_image_for_inference") as mock_submit,
            ):
                mock_submit.return_value = mock_response
                edge_manager = EdgeInferenceManager(db_manager=_fake_db(minimal_compatible=True))
                edge_manager.MODEL_REPOSITORY = temp_dir  # type: ignore
                output = edge_manager.run_inference(detector_id, b"test_image", "image/jpeg", mode=ModeEnum.BINARY)

                assert output["mlb_key"] == "prim_ksuid_only"
                assert "oodd_mlb_key" not in output

    def test_run_inference_missing_model_id_is_nonfatal(self):
        """Missing model_id.txt should simply omit the keys without raising or affecting inference."""
        mock_response = {
            "multi_predictions": None,
            "predictions": {"confidences": [0.54], "labels": [0]},
            "secondary_predictions": None,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            # No model_id.txt written; repository is empty.
            with mock.patch("app.core.edge_inference.submit_image_for_inference") as mock_submit:
                mock_submit.return_value = mock_response
                edge_manager = EdgeInferenceManager(db_manager=_fake_db())
                edge_manager.MODEL_REPOSITORY = temp_dir  # type: ignore
                output = edge_manager.run_inference("test_detector", b"test_image", "image/jpeg", mode=ModeEnum.BINARY)

                assert "mlb_key" not in output
                assert "oodd_mlb_key" not in output

    def test_uses_separate_oodd_caches_db_read(self):
        """Second call for the same detector_id is served from cache; DB is read only once."""
        with mock.patch("app.core.inference_image.INFERENCE_IMAGE_MODE", "minimal_if_compatible"):
            db = _fake_db(minimal_compatible=False)  # not minimal → uses_separate_oodd=True
            edge_manager = EdgeInferenceManager(db_manager=db)

            result1 = edge_manager.uses_separate_oodd("cache_test_detector")
            result2 = edge_manager.uses_separate_oodd("cache_test_detector")

            assert result1 is True
            assert result2 is True
            assert db.get_inference_deployment_record.call_count == 1

    def test_uses_separate_oodd_default_on_missing_row(self):
        """No DB row → conservative default: run separate OODD (full image expected)."""
        with mock.patch("app.core.inference_image.INFERENCE_IMAGE_MODE", "minimal_if_compatible"):
            db = mock.Mock()
            db.get_inference_deployment_record.return_value = None
            edge_manager = EdgeInferenceManager(db_manager=db)

            result = edge_manager.uses_separate_oodd("missing_row_detector")

            assert result is True

    def test_uses_separate_oodd_cache_is_keyed_by_detector_id(self):
        """Two detectors with different minimal_compatible values must get independent cache entries."""
        with mock.patch("app.core.inference_image.INFERENCE_IMAGE_MODE", "minimal_if_compatible"):
            rec_a = mock.Mock()
            rec_a.minimal_compatible = True  # detA is minimal → uses_separate_oodd=False

            rec_b = mock.Mock()
            rec_b.minimal_compatible = False  # detB is full → uses_separate_oodd=True

            db = mock.Mock()
            db.get_inference_deployment_record.side_effect = (
                lambda detector_id, is_oodd=False: rec_a if detector_id == "detA" else rec_b
            )

            edge_manager = EdgeInferenceManager(db_manager=db)

            assert edge_manager.uses_separate_oodd("detA") is False
            assert edge_manager.uses_separate_oodd("detB") is True

    def test_sync_models_skips_oodd_when_minimal_compatible(
        self, edge_model_info_with_binary, oodd_model_info_with_binary
    ):
        """In minimal_if_compatible mode with minimal_compatible=True, OODD model dir is never written."""
        edge_model_info_with_binary.minimal_compatible = True
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            mock.patch("app.core.edge_inference.fetch_model_info") as mock_fetch,
            mock.patch("app.core.edge_inference.get_object_using_presigned_url") as mock_get_from_s3,
            mock.patch("app.core.edge_inference.INFERENCE_IMAGE_MODE", "minimal_if_compatible"),
        ):
            mock_get_from_s3.return_value = b"test_model"
            mock_fetch.return_value = (edge_model_info_with_binary, oodd_model_info_with_binary)
            edge_manager = EdgeInferenceManager(db_manager=_fake_db(minimal_compatible=True))
            edge_manager.MODEL_REPOSITORY = temp_dir  # type: ignore
            detector_id = "test_detector"

            new_model, minimal_compatible = edge_manager.sync_models_from_cloud(detector_id)

            assert new_model is True
            assert minimal_compatible is True
            validate_model_directory(temp_dir, detector_id, 1, edge_model_info_with_binary)
            oodd_dir = os.path.join(temp_dir, detector_id, "oodd")
            assert not os.path.exists(oodd_dir), "OODD dir must not be created when running in minimal mode"
