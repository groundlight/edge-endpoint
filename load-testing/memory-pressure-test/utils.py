import numpy as np
import random
from datetime import datetime
from groundlight import Groundlight, ROI
import math
import cv2

import os
import requests
import json

IMAGE_DIMENSIONS = (480, 640, 3)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)

# We need to establish a client here so that we can use functions like `gl.create_roi`, but we won't
# actually use it to submit anything to Groundlight
gl = Groundlight(endpoint=None)

class APIError(Exception):
    """Any response from the Groundlight API that is not 200
    """
    pass

def call_reef_api(gl_client: Groundlight, path: str, params: dict) -> dict:
    """Given a Groundlight client, an API resource path and API parameters, calls 
    the Groundlight API and returns the decoded response content.

    Submits the Groundlight API token to the API as an X-API-Token.

    Uses the Groundlight client to discover the correct endpoint.
    """

    url = gl_client.endpoint.replace('/device-api', '/reef-api') + path

    headers = {
        "X-API-Token": os.environ.get('GROUNDLIGHT_API_TOKEN')
    }
    
    response = requests.get(url, params=params, headers=headers)
    if response.status_code == 200:
        response_content = response.content.decode('utf-8')
        return json.loads(response_content)
    else:
        raise APIError(
            f"Request failed with status code {response.status_code} | "
            f"Response content: {response.content}" 
            )

def get_detector_stats(gl: Groundlight, detector_id: str) -> dict:
    path = f'/detectors/{detector_id}'
    params = {
        'type': 'summary',
        'answer_type': 'current_best_answer',
    }
    
    decoded_response = call_reef_api(gl, path, params)
    
    yes_labels = decoded_response['ground_truths']['yes']
    no_labels = decoded_response['ground_truths']['no']
    total_labels = yes_labels + no_labels
        
    evaluation_results = decoded_response.get('evaluation_results')
    if evaluation_results is None:
        projected_ml_accuracy = None
    else:
        projected_ml_accuracy = evaluation_results['kfold_pooled__balanced_accuracy']

    return {
        "projected_ml_accuracy": projected_ml_accuracy,
        "total_labels": total_labels,
        "yes_labels": yes_labels,
        "no_labels": no_labels,
        }
    
def get_random_binary_image() -> tuple[np.ndarray, str]:
    """
    Used for generating random data to submit to Groundlight for load testing.
     
    Randomly generates either a black or white image, with the datetime overlaid.
    
    Returns the image and the corresponding label.
    """
    if random.choice([True, False]):
        image = np.zeros(IMAGE_DIMENSIONS, dtype=np.uint8)  # Black image
        text_color = WHITE
        label = "YES"
    else:
        image = np.full(IMAGE_DIMENSIONS, 255, dtype=np.uint8)  # White image
        text_color = BLACK
        label = "NO"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cv2.putText(image, timestamp, (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, text_color, 2)
    return image, label

def get_random_color() -> tuple[int, int, int]:
    return tuple(int(x) for x in np.random.randint(0, 256, 3))

def generate_color_canvas(width: int, height: int, color: tuple[int, int, int]) -> np.ndarray:
    return np.full((height, width, 3), color, dtype=np.uint8)

def generate_random_count_image(
        class_name: str,
        max_count: int = 10,
        image_width: int = 640,
        image_height: int = 480,
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

    return image, rois
