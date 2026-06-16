"""Selection matrix for the per-detector image-flavor decision.

Covers 3 modes: {minimal_compatible=True, False, missing DB row}. Each cell asserts both
``detector_image(...)`` and ``detector_uses_minimal_image(...)`` since both go through the
same primitive — the two getters are required to agree.
"""

from unittest import mock

import pytest

from app.core import inference_image

FULL = "ecr/gl-edge-inference:tag"
MINIMAL = "ecr/gl-edge-inference-minimal:tag"


def _db_with(minimal_compatible):
    """Build a DB stub whose primary record reports the given minimal_compatible value.

    Pass ``None`` to model the missing-row case (record is None).
    """
    db = mock.Mock()
    if minimal_compatible is None:
        db.get_inference_deployment_record.return_value = None
    else:
        record = mock.Mock()
        record.minimal_compatible = minimal_compatible
        db.get_inference_deployment_record.return_value = record
    return db


@pytest.fixture(autouse=True)
def _patch_image_uris():
    """Pin the full/minimal URIs to known values regardless of import-time env."""
    with (
        mock.patch.object(inference_image, "FULL_INFERENCE_IMAGE_URI", FULL),
        mock.patch.object(inference_image, "MINIMAL_INFERENCE_IMAGE_URI", MINIMAL),
    ):
        yield


@pytest.mark.parametrize("minimal_compatible", [True, False, None])
def test_standard_mode_always_full(minimal_compatible):
    """``standard`` ignores per-row state and always picks the full image."""
    with mock.patch.object(inference_image, "INFERENCE_IMAGE_MODE", "standard"):
        db = _db_with(minimal_compatible)
        assert inference_image.detector_uses_minimal_image("det", db) is False
        assert inference_image.detector_image("det", db) == FULL


@pytest.mark.parametrize("minimal_compatible", [True, False, None])
def test_fully_minimal_mode_always_minimal(minimal_compatible):
    """``fully_minimal`` ignores per-row state and always picks the minimal image."""
    with mock.patch.object(inference_image, "INFERENCE_IMAGE_MODE", "fully_minimal"):
        db = _db_with(minimal_compatible)
        assert inference_image.detector_uses_minimal_image("det", db) is True
        assert inference_image.detector_image("det", db) == MINIMAL


def test_minimal_if_compatible_with_compatible_row():
    with mock.patch.object(inference_image, "INFERENCE_IMAGE_MODE", "minimal_if_compatible"):
        db = _db_with(True)
        assert inference_image.detector_uses_minimal_image("det", db) is True
        assert inference_image.detector_image("det", db) == MINIMAL


def test_minimal_if_compatible_with_incompatible_row():
    with mock.patch.object(inference_image, "INFERENCE_IMAGE_MODE", "minimal_if_compatible"):
        db = _db_with(False)
        assert inference_image.detector_uses_minimal_image("det", db) is False
        assert inference_image.detector_image("det", db) == FULL


def test_minimal_if_compatible_missing_row_defaults_full():
    """Missing DB row → False (safe default; degrades gracefully into standard for that detector)."""
    with mock.patch.object(inference_image, "INFERENCE_IMAGE_MODE", "minimal_if_compatible"):
        db = _db_with(None)
        assert inference_image.detector_uses_minimal_image("det", db) is False
        assert inference_image.detector_image("det", db) == FULL


def test_minimal_if_compatible_null_minimal_compatible_defaults_full():
    """Row exists but minimal_compatible is NULL (not yet written by the model-updater) → False."""
    with mock.patch.object(inference_image, "INFERENCE_IMAGE_MODE", "minimal_if_compatible"):
        db2 = mock.Mock()
        record = mock.Mock()
        record.minimal_compatible = None
        db2.get_inference_deployment_record.return_value = record
        assert inference_image.detector_uses_minimal_image("det", db2) is False
