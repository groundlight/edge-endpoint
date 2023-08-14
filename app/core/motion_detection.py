import asyncio
from asyncio import Lock

import numpy as np
from framegrab import MotionDetector
from model import ImageQuery
from pydantic import BaseSettings, Field


class MotdetParameterSettings(BaseSettings):
    """
    Read motion detection parameters from environment variables
    """

    motdet_percentage_threshold: float = Field(
        5.0, description="Percent of pixels needed to change before motion is detected."
    )
    motdet_val_threshold: int = Field(
        50, description="The minimum brightness change for a pixel for it to be considered changed."
    )
    enabled: bool = Field(False, description="Determines if motion detection is enabled by default.")
    max_time_between_images: float = Field(
        3600.0,
        description=(
            "Specifies the maximum time (seconds) between images sent to the cloud. This will be honored even if no"
            " motion has been detected. Defaults to 1 hour."
        ),
    )

    class Config:
        env_file = ".env"


class AsyncMotionDetector:
    """Asynchronous motion detector.
    This is a wrapper around MotionDetector that exposes an asynchronous
    execution of `motion_detected` method. Although this method need not be asynchronous
    from a performance standpoint, we want it to be `async` since it will be
    invoked asynchronously from the API.
    """

    def __init__(self, parameters: MotdetParameterSettings):
        self._motion_detector = MotionDetector(
            pct_threshold=parameters.motdet_percentage_threshold, val_threshold=parameters.motdet_val_threshold
        )
        self._previous_image = None
        self.lock = Lock()
        self._image_query_response = None
        self._motion_detection_enabled = parameters.enabled
        self.max_time_between_images = parameters.max_time_between_images

        # Indicates the last time an image query was submitted to the cloud server.
        self._previous_iq_cloud_submission_time = None

    def is_enabled(self) -> bool:
        return self._motion_detection_enabled

    def enable(self) -> None:
        if not self._motion_detection_enabled:
            self._motion_detection_enabled = True

    @property
    def previous_iq_cloud_submission_time(self):
        return self._previous_iq_cloud_submission_time

    @previous_iq_cloud_submission_time.setter
    def previous_iq_cloud_submission_time(self, time: float):
        self._previous_iq_cloud_submission_time = time

    @property
    def image_query_response(self):
        """
        Get the image query response from the last motion detection run.
        We are using `image_query_response` as a property so that we can
        store the cloud's response and readily return it if the next image
        has no motion.
        """
        return self._image_query_response

    @image_query_response.setter
    def image_query_response(self, response: ImageQuery):
        self._image_query_response = response

    async def motion_detected(self, new_img: np.ndarray) -> bool:
        return await asyncio.to_thread(self._motion_detector.motion_detected, new_img)
