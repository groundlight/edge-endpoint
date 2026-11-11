import io
import random
import threading
import types
from datetime import datetime

from groundlight.images import parse_supported_image_types
from PIL import Image

import image_helpers as imgh
from app_benchmark import lenses


class _FakeClient:
    """Stands in for ExperimentalApi: records every submitted image, answers from edge."""

    def __init__(self):
        self.calls = []
        self._lock = threading.Lock()

    def ask_ml(self, detector_id, image):
        with self._lock:
            self.calls.append((detector_id, image.copy()))
        return types.SimpleNamespace(detector_id=detector_id, result=types.SimpleNamespace(from_edge=True))


def _decoded_pixels(image):
    """The pixels the edge feature cache keys on: SDK JPEG encode, then decode."""
    jpeg = parse_supported_image_types(image).read()
    return Image.open(io.BytesIO(jpeg)).convert("RGB").tobytes()


def test_bbox_to_binary_sends_distinct_pixels_on_every_binary_call(monkeypatch, tmp_path):
    client = _FakeClient()
    monkeypatch.setattr(lenses, "ExperimentalApi", lambda endpoint: client)
    monkeypatch.setattr(lenses, "_silence_stderr", lambda: None)
    objects = 4

    lenses.run_bbox_to_binary(
        worker_number=0, camera=0, lens_name="lens", copy_index=0,
        bbox_detector_id="det_bbox", binary_detector_id="det_binary", objects=objects,
        edge_url="http://edge", image_size=(64, 48), target_fps=0,
        duration_seconds=0.1, log_file=str(tmp_path / "camera.log"),
    )

    binary_pixels = [_decoded_pixels(img) for det, img in client.calls if det == "det_binary"]
    assert len(binary_pixels) >= 2 * objects  # spans multiple frames, not just one fan-out
    assert len(set(binary_pixels)) == len(binary_pixels)


def test_binary_image_tag_alone_distinguishes_pixels(monkeypatch):
    # Same color and timestamp is what two cameras hitting the same pod in the same millisecond produce.
    fixed_now = datetime(2026, 1, 1, 12, 0, 0, 123000)
    monkeypatch.setattr(imgh, "datetime", types.SimpleNamespace(now=lambda: fixed_now))

    def render(tag):
        random.seed(0)
        image, _, _ = imgh.generate_random_binary_image(224, 224, tag=tag)
        return _decoded_pixels(image)

    assert render("0-2") == render("0-2")
    assert render("0-2") != render("1-2")
