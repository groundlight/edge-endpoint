import numpy as np
import random
from datetime import datetime
from groundlight import ExperimentalApi, ROI, Detector
import math
import cv2

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)

def get_random_color() -> tuple[int, int, int]:
    """Return a random RGB color tuple."""
    return tuple(int(x) for x in np.random.randint(0, 256, 3))


def generate_color_canvas(width: int, height: int, color: tuple[int, int, int]) -> np.ndarray:
    """Return a solid-color image as a numpy array."""
    return np.full((height, width, 3), color, dtype=np.uint8)


def generate_random_binary_image(
    gl: ExperimentalApi,  # not used, but kept for consistency with other generators
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

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cv2.putText(image, timestamp, (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, text_color, 2)

    return image, label, None


def generate_random_objects_image(
    gl: ExperimentalApi,
    image_width: int = 640,
    image_height: int = 480,
    class_name: str = 'object',
    max_count: int = 10,
) -> tuple[np.ndarray, int, list[ROI]]:
    """Generate an image containing a random number of objects (drawn as circles), with the object count and per-object ROIs."""
    count = random.randint(0, max_count)

    image_diagonal = math.sqrt(image_width ** 2 + image_height ** 2)
    min_circle_radius = int(image_diagonal * 0.05)
    max_circle_radius = int(image_diagonal * 0.07)

    canvas_color = get_random_color()
    image = generate_color_canvas(image_width, image_height, canvas_color)

    rois: list[ROI] = []
    for _ in range(count):
        circle_color = get_random_color()
        circle_radius = random.randint(min_circle_radius, max_circle_radius)
        circle_x = random.randint(circle_radius, image_width - circle_radius)
        circle_y = random.randint(circle_radius, image_height - circle_radius)

        cv2.circle(image, (circle_x, circle_y), circle_radius, circle_color, -1)

        top_left = (
            (circle_x - circle_radius) / image_width,
            (circle_y - circle_radius) / image_height,
        )
        bottom_right = (
            (circle_x + circle_radius) / image_width,
            (circle_y + circle_radius) / image_height,
        )

        roi = gl.create_roi(
            label=class_name,
            top_left=top_left,
            bottom_right=bottom_right,
        )
        rois.append(roi)

    label = len(rois)
    return image, label, rois


def generate_random_multiclass_image(
    gl: ExperimentalApi,  # not used, but kept for consistency with other generators
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
    gl: ExperimentalApi,
    detector: Detector,
    image_width: int,
    image_height: int,
) -> tuple[np.ndarray, int | str, list[ROI]] | None:
    """Dispatch to the appropriate image generator based on the detector's mode."""
    detector_mode = detector.mode
    if detector_mode == 'COUNT':
        detector_mode_configuration = detector.mode_configuration
        class_name = detector_mode_configuration["class_name"]
        max_count = int(detector_mode_configuration["max_count"])
        image, label, rois = generate_random_objects_image(
            gl,
            image_width=image_width,
            image_height=image_height,
            class_name=class_name,
            max_count=max_count,
        )
    elif detector_mode == 'BOUNDING_BOX':
        config = detector.mode_configuration
        class_name = config["class_name"]
        max_num_bboxes = int(config.get("max_num_bboxes", 10))
        image, _, rois = generate_random_objects_image(
            gl,
            image_width=image_width,
            image_height=image_height,
            class_name=class_name,
            max_count=max_num_bboxes,
        )
        label = "BOUNDING_BOX" if rois else "NO_OBJECTS"
    elif detector_mode == 'BINARY':
        image, label, rois = generate_random_binary_image(
            gl,
            image_width=image_width,
            image_height=image_height,
        )
    elif detector_mode == 'MULTI_CLASS':
        class_names = list(detector.mode_configuration["class_names"])
        image, label, rois = generate_random_multiclass_image(
            gl,
            class_names,
            image_width=image_width,
            image_height=image_height,
        )
    else:
        raise ValueError(
            f'Unsupported detector mode of {detector_mode} for {detector.id}'
        )

    return image, label, rois


