"""Tests for CompositeGenerator: reproducibility, count clamping, ROI sanity."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from app_benchmark.config import ImageConfig
from app_benchmark.image_loader import (
    CompositeGenerator,
    crop_from_roi,
    load_padding_jpeg,
)

_BASE = Path(__file__).resolve().parents[2] / "images" / "dog.jpeg"
_PADDING = Path(__file__).resolve().parents[2] / "images" / "cat.jpeg"


@pytest.fixture
def img_cfg() -> ImageConfig:
    return ImageConfig(base=str(_BASE), resolution=(640, 480), composite_objects=None, seed=42)


def test_composite_generator_reproducible(img_cfg):
    g1 = CompositeGenerator(img_cfg, camera_idx=0)
    g2 = CompositeGenerator(img_cfg, camera_idx=0)
    f1 = g1.next(max_objects=5)
    f2 = g2.next(max_objects=5)
    assert f1.composite_objects_count == f2.composite_objects_count
    assert f1.canvas_jpeg == f2.canvas_jpeg
    assert f1.rois == f2.rois


def test_different_cameras_diverge(img_cfg):
    g1 = CompositeGenerator(img_cfg, camera_idx=0)
    g2 = CompositeGenerator(img_cfg, camera_idx=1)
    f1 = g1.next(max_objects=5)
    f2 = g2.next(max_objects=5)
    assert f1.canvas_jpeg != f2.canvas_jpeg


def test_count_clamped_to_at_least_one(img_cfg):
    gen = CompositeGenerator(img_cfg, camera_idx=0)
    for _ in range(20):
        f = gen.next(max_objects=1)
        assert f.composite_objects_count >= 1
        assert f.composite_objects_count <= 1


def test_count_within_max(img_cfg):
    gen = CompositeGenerator(img_cfg, camera_idx=0)
    for _ in range(20):
        f = gen.next(max_objects=3)
        assert 1 <= f.composite_objects_count <= 3


def test_rois_within_canvas(img_cfg):
    canvas_w, canvas_h = img_cfg.resolution
    gen = CompositeGenerator(img_cfg, camera_idx=0)
    for _ in range(10):
        f = gen.next(max_objects=5)
        for roi in f.rois:
            assert 0 <= roi.x and roi.x + roi.w <= canvas_w
            assert 0 <= roi.y and roi.y + roi.h <= canvas_h


def test_crop_from_roi_resizes_correctly(img_cfg):
    gen = CompositeGenerator(img_cfg, camera_idx=0)
    f = gen.next(max_objects=3)
    if not f.rois:
        return
    crop_bytes = crop_from_roi(f.canvas_jpeg, f.rois[0], (224, 224))
    arr = np.frombuffer(crop_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    assert img is not None
    assert img.shape[:2] == (224, 224)


def test_load_padding_jpeg(tmp_path):
    if not _PADDING.is_file():
        pytest.skip(f"padding image not present at {_PADDING}")
    blob = load_padding_jpeg(_PADDING, (224, 224))
    arr = np.frombuffer(blob, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    assert img is not None
    assert img.shape[:2] == (224, 224)


def test_invalid_max_objects_raises(img_cfg):
    gen = CompositeGenerator(img_cfg, camera_idx=0)
    with pytest.raises(ValueError):
        gen.next(max_objects=0)
