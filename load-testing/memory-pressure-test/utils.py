import numpy as np
import random
import groundlight
from groundlight import ROI, Groundlight
import math
import cv2

from datetime import datetime

IMAGE_DIMENSIONS = (480, 640, 3)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)

def generate_random_binary_image(
    gl: Groundlight,  # not used, but added here to maintain consistency with `generate_random_count_image`
    image_width: int = 640,
    image_height: int = 480,
) -> tuple[np.ndarray, str]:
    """
    Used for generating random data to submit to Groundlight for load testing.
    
    Randomly generates either a black or white image of the specified dimensions,
    with the datetime overlaid.

    Returns:
        tuple: (image as np.ndarray, label as str)
    """
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

    return image, label, None # return rois as None to maintain consistency with `generate_random_count_image` 

def get_random_color() -> tuple[int, int, int]:
    return tuple(int(x) for x in np.random.randint(0, 256, 3))

def generate_color_canvas(width: int, height: int, color: tuple[int, int, int]) -> np.ndarray:
    return np.full((height, width, 3), color, dtype=np.uint8)

def generate_random_count_image(
        gl: Groundlight,
        image_width: int = 640,
        image_height: int = 480,
        class_name: str = 'object',
        max_count: int = 10,
    ) -> tuple[np.ndarray, list[ROI]]:
    """
    Used for generating random data to submit to Groundlight for load testing.
     
    Generates an image with a random number of circles.
    
    Returns the image and a list of ROI objects, which can be submitted as a label to Groundlight.
    """

    count = random.randint(0, max_count)

    # Determine minimum and maximum size of circle radius based on some constants
    # and the diagonal length of the image
    image_diagonal = math.sqrt(image_width ** 2 + image_height ** 2)
    min_circle_radius = int(image_diagonal * 0.05)
    max_circle_radius = int(image_diagonal * 0.07)

    # Generate a image of image_dimensions size, choose a random color for the background
    canvas_color = get_random_color()
    image = generate_color_canvas(image_width, image_height, canvas_color)

    rois = []
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
            (circle_y + circle_radius) / image_height
            )

        roi = gl.create_roi(
            label=class_name,
            top_left=top_left,
            bottom_right=bottom_right,
        )
        rois.append(roi)

    label = len(rois)

    return image, label, rois
