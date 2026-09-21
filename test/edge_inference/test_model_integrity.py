import hashlib
import json
import os
import tempfile
from unittest import mock

import pytest

from app.core.edge_inference import (
    MODEL_INTEGRITY_FILENAME,
    get_all_model_versions,
    get_model_buffer,
    save_models_to_repository,
    verify_downloaded_buffer,
)
from app.core.utils import ModelInfoWithBinary


def _info_with_hash(payload: bytes, digest: str | None = None, length: int | None = None) -> ModelInfoWithBinary:
    return ModelInfoWithBinary(
        pipeline_config="test_pipeline_config",
        predictor_metadata='{"text_query":"q","mode":"BINARY"}',
        model_binary_id="test_binary_id",
        model_binary_url="http://example.test/model",
        payload_sha384=hashlib.sha384(payload).hexdigest() if digest is None else digest,
        payload_length=len(payload) if length is None else length,
    )


def test_verify_downloaded_buffer_raises_on_hash_mismatch():
    payload = b"trusted-bytes"
    info = _info_with_hash(payload, digest=hashlib.sha384(b"other").hexdigest())
    with pytest.raises(RuntimeError, match="hash mismatch"):
        verify_downloaded_buffer(info, payload)


def test_verify_downloaded_buffer_raises_on_length_mismatch():
    payload = b"short"
    info = _info_with_hash(payload, length=99)
    with pytest.raises(RuntimeError, match="length mismatch"):
        verify_downloaded_buffer(info, payload)


def test_verify_downloaded_buffer_raises_when_cloud_omits_fields():
    info = ModelInfoWithBinary(
        pipeline_config="test_pipeline_config",
        predictor_metadata="{}",
        model_binary_id="id",
        model_binary_url="http://example.test/model",
    )
    with pytest.raises(RuntimeError, match="omitted payload integrity fields"):
        verify_downloaded_buffer(info, b"legacy-bytes")


def test_get_model_buffer_raises_on_hash_mismatch():
    info = _info_with_hash(b"good")
    with mock.patch("app.core.edge_inference.get_object_using_presigned_url", return_value=b"evil"):
        with pytest.raises(RuntimeError, match="hash mismatch"):
            get_model_buffer(info)


def test_save_writes_integrity_sidecar_when_hash_fields_present():
    payload = b"trusted-bytes"
    info = _info_with_hash(payload)
    with tempfile.TemporaryDirectory() as temp_dir:
        save_models_to_repository(
            detector_id="det",
            edge_model_buffer=payload,
            edge_model_info=info,
            oodd_model_buffer=None,
            oodd_model_info=None,
            repository_root=temp_dir,
        )
        sidecar = os.path.join(temp_dir, "det", "primary", "1", MODEL_INTEGRITY_FILENAME)
        assert os.path.isfile(sidecar)
        body = json.loads(open(sidecar).read())
        assert body["payload_sha384"] == hashlib.sha384(payload).hexdigest()
        assert body["payload_length"] == len(payload)
        assert not os.path.exists(os.path.join(temp_dir, "det", "primary", ".tmp-1"))


def test_get_all_model_versions_ignores_staging_directories():
    with tempfile.TemporaryDirectory() as temp_dir:
        os.makedirs(os.path.join(temp_dir, "1"))
        os.makedirs(os.path.join(temp_dir, ".tmp-2"))
        assert get_all_model_versions(temp_dir) == [1]
