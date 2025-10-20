import numpy as np
import random
from datetime import datetime
from groundlight import Groundlight, ROI, Detector, ApiException, ImageQuery
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
    total_labels = decoded_response['total_iqs']
        
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

def generate_random_binary_image(
    gl: Groundlight,  # not used, but added here to maintain consistency with `generate_random_count_image`
    image_width: int = 640,
    image_height: int = 480,
) -> tuple[np.ndarray, str, None]:
    """
    Used for generating random data to submit to Groundlight for load testing.
    
    Randomly generates either a black or white image of the specified dimensions,
    with the datetime overlaid.

    Returns:
        tuple: (image as np.ndarray, label as str, rois as None)
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
    ) -> tuple[np.ndarray, int, list[ROI]]:
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

def get_or_create_count_detector(
    gl: Groundlight,
    name: str,
    class_name: str,
    max_count: int, 
    group_name: str,
    ) -> list[Detector]:

    query_text = f"Count all the {class_name}s"
    try:
        return gl.create_counting_detector(
            name,
            query_text,
            class_name,
            max_count=max_count,
            group_name=group_name,
        )
    except ApiException as e:
        if e.status != 400 or "unique_undeleted_name_per_set" not in getattr(e, "body", ""):
            raise
        return gl.get_detector_by_name(name)

def error_if_not_from_edge(iq: ImageQuery) -> None:
    if not iq.result.from_edge:
        raise ValueError(
            'Got a non-edge answer from the Edge Endpoint. '
            f'Please configure your Edge Endpoint so that {iq.detector_id} always receives edge answers.'
        )

def prime_detector(
    gl: Groundlight, 
    detector: Detector, 
    num_labels: int, 
    image_width: int, 
    image_height: int) -> None:
    """
    Submits a handful of labels to a detector so that the cloud can train a model. 
    """
    for _ in range(num_labels):
        if detector.mode == 'COUNT':
            class_name = detector.mode_configuration["class_name"]
            max_count = detector.mode_configuration["max_count"]
            image, label, rois = generate_random_count_image(
                gl, 
                image_width=image_width, 
                image_height=image_height, 
                class_name=class_name,
                max_count=max_count,
                )

            iq = gl.ask_async(detector, image, human_review="NEVER")
            gl.add_label(iq, label, rois)

def detector_is_sufficiently_trained(
    stats: dict,
    min_projected_ml_accuracy: float,
    min_total_labels: int,
    ) -> bool:
    projected_ml_accuracy = stats['projected_ml_accuracy'] 
    total_labels = stats['total_labels'] 
    return projected_ml_accuracy is not None and \
        projected_ml_accuracy > min_projected_ml_accuracy and \
        total_labels >= min_total_labels
