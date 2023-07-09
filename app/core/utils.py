import cv2
import numpy as np
import requests
from PIL import Image
from fastapi import Request


def get_groundlight_instance(request: Request):
    return request.app.state.groundlight


def get_motion_detector_instance(request: Request):
    return request.app.state.motion_detector


def get_numpy_image(image_filename: str) -> np.ndarray:
    if image_filename.startswith("http"):
        image = Image.open(requests.get(image_filename, stream=True).raw)
        return np.array(image)
    elif image_filename.endswith(("jpeg", "jpg")):
        # Return a numpy array in BGR format
        return cv2.imread(filename=image_filename)

    raise ValueError(f"Unsupported input image: {image_filename}")
