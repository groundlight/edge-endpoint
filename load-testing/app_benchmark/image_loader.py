"""Per-camera composite image generation + ground-truth crops + padding."""

import random
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app_benchmark.config import ImageConfig

_BACKGROUND_COLOR_THRESHOLD = 240
_WHITE = (255, 255, 255)
_JPEG_QUALITY = 90


@dataclass(frozen=True)
class ROI:
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class GeneratedFrame:
    canvas_jpeg: bytes
    rois: list[ROI]
    composite_objects_count: int


def _load_base(path: str) -> tuple[np.ndarray, np.ndarray]:
    """Load base image and compute its near-white background mask."""
    img = cv2.imread(path)
    if img is None:
        raise FileNotFoundError(f"Could not read base image: {path}")
    mask = ~np.all(img >= _BACKGROUND_COLOR_THRESHOLD, axis=2)
    return img, mask


def _solid_canvas(width: int, height: int) -> np.ndarray:
    return np.full((height, width, 3), _WHITE, dtype=np.uint8)


def _place(canvas: np.ndarray, base: np.ndarray, base_mask: np.ndarray,
           x: int, y: int, dw: int, dh: int) -> None:
    resized = cv2.resize(base, (dw, dh), interpolation=cv2.INTER_AREA)
    mask = cv2.resize(base_mask.astype(np.uint8), (dw, dh), interpolation=cv2.INTER_NEAREST).astype(bool)
    canvas[y:y + dh, x:x + dw][mask] = resized[mask]


def _encode_jpeg(canvas: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".jpg", canvas, [int(cv2.IMWRITE_JPEG_QUALITY), _JPEG_QUALITY])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return buf.tobytes()


class CompositeGenerator:
    """Generates per-frame composite images for a single camera.

    Each camera has its own random.Random instance (seeded from
    image.seed + camera_idx * 9973) so cameras within a lens diverge but each
    is reproducible across runs.
    """

    def __init__(self, image_cfg: ImageConfig, camera_idx: int) -> None:
        self.cfg = image_cfg
        self._rng = random.Random(image_cfg.seed + camera_idx * 9973)
        self._base, self._mask = _load_base(image_cfg.base)
        self._base_h, self._base_w = self._base.shape[:2]

    def next(self, max_objects: int) -> GeneratedFrame:
        if max_objects < 1:
            raise ValueError(f"max_objects must be >= 1 (got {max_objects})")
        canvas_w, canvas_h = self.cfg.resolution
        canvas = _solid_canvas(canvas_w, canvas_h)
        count = self._rng.randint(1, max_objects)

        short_side = min(canvas_w, canvas_h)
        min_size = max(1, int(short_side * 0.10))
        max_size = max(min_size, int(short_side * 0.25))

        rois: list[ROI] = []
        for _ in range(count):
            target = self._rng.randint(min_size, max_size)
            scale = target / max(self._base_w, self._base_h)
            dw = max(1, int(self._base_w * scale))
            dh = max(1, int(self._base_h * scale))
            if dw > canvas_w or dh > canvas_h:
                continue
            x = self._rng.randint(0, canvas_w - dw)
            y = self._rng.randint(0, canvas_h - dh)
            _place(canvas, self._base, self._mask, x, y, dw, dh)
            rois.append(ROI(x=x, y=y, w=dw, h=dh))

        return GeneratedFrame(
            canvas_jpeg=_encode_jpeg(canvas),
            rois=rois,
            composite_objects_count=len(rois),
        )


def crop_from_roi(canvas_jpeg: bytes, roi: ROI, resize_to: tuple[int, int]) -> bytes:
    arr = np.frombuffer(canvas_jpeg, dtype=np.uint8)
    canvas = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if canvas is None:
        raise RuntimeError("Failed to decode canvas JPEG")
    crop = canvas[roi.y:roi.y + roi.h, roi.x:roi.x + roi.w]
    target_w, target_h = resize_to
    resized = cv2.resize(crop, (target_w, target_h), interpolation=cv2.INTER_AREA)
    return _encode_jpeg(resized)


def load_padding_jpeg(path: str | Path, resize_to: tuple[int, int]) -> bytes:
    """Decode + resize + JPEG-encode a padding image. Cached at lens startup."""
    img = cv2.imread(str(path))
    if img is None:
        raise FileNotFoundError(f"Could not read padding image: {path}")
    target_w, target_h = resize_to
    resized = cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_AREA)
    return _encode_jpeg(resized)
