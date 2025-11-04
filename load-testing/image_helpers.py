import numpy as np
import random
from datetime import datetime
from groundlight import ExperimentalApi, ROI, Detector
import math
import cv2

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)

def get_random_color() -> tuple[int, int, int]:
    return tuple(int(x) for x in np.random.randint(0, 256, 3))


def generate_color_canvas(width: int, height: int, color: tuple[int, int, int]) -> np.ndarray:
    return np.full((height, width, 3), color, dtype=np.uint8)


def generate_random_binary_image(
    gl: ExperimentalApi,  # not used, but kept for consistency with other generators
    image_width: int = 640,
    image_height: int = 480,
) -> tuple[np.ndarray, str, None]:
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


def generate_random_count_image(
    gl: ExperimentalApi,
    image_width: int = 640,
    image_height: int = 480,
    class_name: str = 'object',
    max_count: int = 10,
) -> tuple[np.ndarray, int, list[ROI]]:
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


def generate_random_image(
    gl: ExperimentalApi,
    detector: Detector,
    image_width: int,
    image_height: int,
) -> tuple[np.ndarray, int | str, list[ROI]] | None:
    detector_mode = detector.mode
    if detector_mode == 'COUNT':
        detector_mode_configuration = detector.mode_configuration
        class_name = detector_mode_configuration["class_name"]
        max_count = int(detector_mode_configuration["max_count"])
        image, label, rois = generate_random_count_image(
            gl,
            image_width=image_width,
            image_height=image_height,
            class_name=class_name,
            max_count=max_count,
        )
    elif detector_mode == 'BINARY':
        image, label, rois = generate_random_binary_image(
            gl,
            image_width=image_width,
            image_height=image_height,
        )
    else:
        raise ValueError(
            f'Unsupported detector mode of {detector_mode} for {detector.id}'
        )

    return image, label, rois


