import numpy as np
from PIL import Image
import requests
import cv2


def get_numpy_image(image_filename: str) -> np.ndarray:
    if image_filename.startswith("http"):
        image = Image.open(requests.get(image_filename, stream=True).raw)
        return np.array(image)
    elif image_filename.endswith("jpeg"):
        # Return a numpy array in BGR format
        return cv2.imread(filename=image_filename)

    raise ValueError(f"Unsupported input image: {image_filename}")
