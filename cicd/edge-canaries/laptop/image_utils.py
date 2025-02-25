import cv2
import numpy as np

def resize_image(image: np.ndarray, target_width: int) -> np.ndarray:
    """Resize an image to a specified width while maintaining the aspect ratio."""
    height, width = image.shape[:2]
    scale_factor = target_width / width
    target_height = int(height * scale_factor)
    return cv2.resize(image, (target_width, target_height), interpolation=cv2.INTER_AREA)
