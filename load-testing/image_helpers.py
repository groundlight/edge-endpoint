import numpy as np
import random
from datetime import datetime
from groundlight import Detector
from model import ROI, BBoxGeometry
import cv2
from pathlib import Path

from constants import OBJECT_DETECTION_CLASS_NAME

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)

def get_random_color() -> tuple[int, int, int]:
    """Return a random RGB color tuple."""
    return tuple(int(x) for x in np.random.randint(0, 256, 3))


def generate_color_canvas(width: int, height: int, color: tuple[int, int, int]) -> np.ndarray:
    """Return a solid-color image as a numpy array."""
    return np.full((height, width, 3), color, dtype=np.uint8)


def _make_roi(label: str, x: int, y: int, dw: int, dh: int, image_width: int, image_height: int) -> ROI:
    """Construct an ROI from pixel coordinates, normalizing to [0, 1]."""
    left = x / image_width
    top = y / image_height
    right = (x + dw) / image_width
    bottom = (y + dh) / image_height
    return ROI(
        label=label,
        score=1.0,
        geometry=BBoxGeometry(
            left=left, top=top, right=right, bottom=bottom,
            x=(left + right) / 2, y=(top + bottom) / 2,
        ),
    )


OBJECT_DETECTION_IMAGE: np.ndarray = cv2.imread(str(Path(__file__).parent / "images" / "dog.jpeg"))
assert OBJECT_DETECTION_IMAGE is not None, "Failed to load dog.jpeg -- check that load-testing/images/dog.jpeg exists"

# Pixels at or above this value (per channel) are treated as background and masked out during compositing.
# Set below 255 to absorb near-white JPEG compression artifacts at the edges of the image.
_BACKGROUND_COLOR_THRESHOLD = 240
_OBJECT_DETECTION_MASK: np.ndarray = ~np.all(OBJECT_DETECTION_IMAGE >= _BACKGROUND_COLOR_THRESHOLD, axis=2)


def _place_object(canvas: np.ndarray, x: int, y: int, dw: int, dh: int) -> None:
    """Resize OBJECT_DETECTION_IMAGE to (dw, dh) and place it onto canvas at (x, y), masking near-white pixels."""
    resized = cv2.resize(OBJECT_DETECTION_IMAGE, (dw, dh), interpolation=cv2.INTER_AREA)
    mask = cv2.resize(_OBJECT_DETECTION_MASK.astype(np.uint8), (dw, dh), interpolation=cv2.INTER_NEAREST).astype(bool)
    canvas[y:y + dh, x:x + dw][mask] = resized[mask]


def generate_random_objects_image(
    image_width: int = 640,
    image_height: int = 480,
    max_count: int = 10,
) -> tuple[np.ndarray, int, list[ROI]]:
    """Generate a white canvas with a random number of object images placed at random positions, with per-object ROIs.

    Dogs are composited with a near-white transparency mask so their backgrounds don't occlude one another.
    """
    h, w = OBJECT_DETECTION_IMAGE.shape[:2]

    count = random.randint(0, max_count)
    canvas = generate_color_canvas(image_width, image_height, WHITE)

    short_side = min(image_width, image_height)
    min_size = max(1, int(short_side * 0.10))
    max_size = max(min_size, int(short_side * 0.25))

    rois: list[ROI] = []
    for _ in range(count):
        target_size = random.randint(min_size, max_size)
        scale = target_size / max(w, h)
        dw = max(1, int(w * scale))
        dh = max(1, int(h * scale))

        if dw > image_width or dh > image_height:
            continue

        x = random.randint(0, max(0, image_width - dw))
        y = random.randint(0, max(0, image_height - dh))

        _place_object(canvas, x, y, dw, dh)
        rois.append(_make_roi(OBJECT_DETECTION_CLASS_NAME, x, y, dw, dh, image_width, image_height))

    return canvas, len(rois), rois


def generate_random_binary_image(
    image_width: int = 640,
    image_height: int = 480,
) -> tuple[np.ndarray, str, None]:
    """Generate a random black or white image with a timestamp overlay and matching YES/NO label."""
    image_shape = (image_height, image_width, 3)

    if random.choice([True, False]):
        image = np.zeros(image_shape, dtype=np.uint8)  # Black image
        text_color = WHITE
        label = "YES"
    else:
        image = np.full(image_shape, 255, dtype=np.uint8)  # White image
        text_color = BLACK
        label = "NO"

    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    font = cv2.FONT_HERSHEY_SIMPLEX
    # Scale relative to the 640x480 baseline so text occupies the same fraction of any image size.
    font_scale = min(image_width / 640.0, image_height / 480.0)
    thickness = max(1, round(font_scale * 2))
    (_, text_h), _ = cv2.getTextSize(timestamp, font, font_scale, thickness)
    margin = max(5, round(image_height * 0.02))
    cv2.putText(image, timestamp, (margin, margin + text_h), font, font_scale, text_color, thickness)

    return image, label, None


def generate_random_multiclass_image(
    class_names: list[str],
    image_width: int = 640,
    image_height: int = 480,
) -> tuple[np.ndarray, str, None]:
    """Generate an image containing one randomly-selected class string drawn at a random size, color, and position.

    The returned label is the chosen class name. No ROIs are returned because multi-class is a
    classification (not detection) problem.
    """
    if not class_names:
        raise ValueError("class_names must be a non-empty list")

    label = random.choice(class_names)

    canvas_color = get_random_color()
    image = generate_color_canvas(image_width, image_height, canvas_color)

    # Pick a target text height as a fraction of image height so the numerals scale with image size
    # and look comparably large regardless of resolution. Lower bound is intentionally generous.
    font = cv2.FONT_HERSHEY_SIMPLEX
    target_text_height_px = random.uniform(image_height * 0.40, image_height * 0.75)
    # For FONT_HERSHEY_SIMPLEX, text height in pixels is ~22 * font_scale (with thickness ~= 2 * font_scale).
    font_scale = target_text_height_px / 22.0
    thickness = max(2, int(font_scale * 2))

    (text_width, text_height), baseline = cv2.getTextSize(label, font, font_scale, thickness)

    # If the rendered text overflows either dimension (long label, small image, or a
    # baseline that pushes the total height past image_height), shrink font_scale to fit.
    shrink = min(1.0, image_width / text_width, image_height / (text_height + baseline))
    if shrink < 1.0:
        font_scale *= shrink
        thickness = max(2, int(font_scale * 2))
        (text_width, text_height), baseline = cv2.getTextSize(label, font, font_scale, thickness)

    # Pick a random position that keeps the rendered text fully inside the image.
    # The max() guards protect against any residual rounding from the shrink above.
    x = random.randint(0, max(0, image_width - text_width))
    y = random.randint(text_height, max(text_height, image_height - baseline))

    text_color = get_random_color()
    cv2.putText(image, label, (x, y), font, font_scale, text_color, thickness)

    return image, label, None


def generate_random_image(
    detector: Detector,
    image_width: int,
    image_height: int,
) -> tuple[np.ndarray, int | str, list[ROI]] | None:
    """Dispatch to the appropriate image generator based on the detector's mode."""
    detector_mode = detector.mode
    if detector_mode == 'COUNT':
        max_count = int(detector.mode_configuration["max_count"])
        image, label, rois = generate_random_objects_image(
            image_width=image_width,
            image_height=image_height,
            max_count=max_count,
        )
    elif detector_mode == 'BOUNDING_BOX':
        max_num_bboxes = int(detector.mode_configuration["max_num_bboxes"])
        image, _, rois = generate_random_objects_image(
            image_width=image_width,
            image_height=image_height,
            max_count=max_num_bboxes,
        )
        label = "BOUNDING_BOX" if rois else "NO_OBJECTS"
    elif detector_mode == 'BINARY':
        image, label, rois = generate_random_binary_image(
            image_width=image_width,
            image_height=image_height,
        )
    elif detector_mode == 'MULTI_CLASS':
        class_names = list(detector.mode_configuration["class_names"])
        image, label, rois = generate_random_multiclass_image(
            class_names,
            image_width=image_width,
            image_height=image_height,
        )
    else:
        raise ValueError(
            f'Unsupported detector mode of {detector_mode} for {detector.id}'
        )

    return image, label, rois
