import asyncio
from asyncio import Lock

import numpy as np
from framegrab import MotionDetector
from model import ImageQuery
from pydantic import BaseSettings


class MotdetParameterSettings(BaseSettings):
    """
    Read motion detection parameters from environment variables
    """

    motdet_percentage_threshold: float
    motdet_val_threshold: int

    class Config:
        env_file = ".env"


class AsyncMotionDetector:
    """Asynchronous motion detector.
    This is a wrapper around MotionDetector that exposes an asynchronous
    execution of `motion_detected` method. Although this method need not be asynchronous
    from a performance standpoint, we want it to be `async` since it will be
    invoked asynchronously from the API.
    """

    def __init__(self, percentage_threshold: float = 1, val_threshold: int = 50):
        self._motion_detector = MotionDetector(pct_threshold=percentage_threshold, val_threshold=val_threshold)
        self._previous_image = None
        self.lock = Lock()
        self._image_query_response = None

    @property
    def image_query_response(self):
        return self._image_query_response

    @image_query_response.setter
    def image_query_response(self, response: ImageQuery):
        self._image_query_response = response

    async def motion_detected(self, new_img: np.ndarray) -> bool:
        return await asyncio.to_thread(self._motion_detector.motion_detected, new_img)
