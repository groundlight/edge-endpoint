import asyncio
import time
from asyncio import Lock

import numpy as np
from framegrab import MotionDetector
from pydantic import BaseSettings, Field


class MotdetParameterSettings(BaseSettings):
    """
    Read motion detection parameters from environment variables
    """

    motion_detection_percentage_threshold: float = Field(
        5.0, description="Percent of pixels needed to change before motion is detected."
    )
    motion_detection_val_threshold: int = Field(
        50, description="The minimum brightness change for a pixel for it to be considered changed."
    )
    motion_detection_enabled: bool = Field(False, description="Determines if motion detection is enabled by default.")
    motion_detection_max_time_between_images: float = Field(
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
            pct_threshold=parameters.motion_detection_percentage_threshold,
            val_threshold=parameters.motion_detection_val_threshold,
        )
        self._previous_image = None
        self.lock = Lock()
        self.image_query_response = None
        self._motion_detection_enabled = parameters.motion_detection_enabled
        self._max_time_between_images = parameters.motion_detection_max_time_between_images

        # Indicates the last time an image query was submitted to the cloud server.
        self.previous_iq_cloud_submission_time = None

    def is_enabled(self) -> bool:
        return self._motion_detection_enabled

    def enable(self) -> None:
        if not self._motion_detection_enabled:
            self._motion_detection_enabled = True

    async def motion_detected(self, new_img: np.ndarray) -> bool:
        if self.previous_iq_cloud_submission_time is not None:
            current_time = time.monotonic()
            if current_time - self.previous_iq_cloud_submission_time > self._max_time_between_images:
                return True
        return await asyncio.to_thread(self._motion_detector.motion_detected, new_img)
