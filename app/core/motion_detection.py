import logging
import time
from typing import Dict, Optional

import numpy as np
from framegrab import MotionDetector
from model import ImageQuery

from .configs import MotionDetectionConfig

logger = logging.getLogger(__name__)


class MotionDetectorWrapper:
    """
    This is a wrapper around MotionDetector from framegrab.
    """

    def __init__(self, parameters: MotionDetectionConfig):
        self._motion_detector = MotionDetector(
            pct_threshold=parameters.percentage_threshold,
            val_threshold=parameters.val_threshold,
        )
        self._previous_image = None
        self.image_query_response: Optional[ImageQuery] = None
        self._motion_detection_enabled = parameters.enabled
        self._max_time_between_images = parameters.max_time_between_images
        self._unconfident_iq_reescalation_interval = parameters.unconfident_iq_reescalation_interval

        # Indicates the last time motion was detected.
        self._previous_motion_detection_time = None

    def is_enabled(self) -> bool:
        return self._motion_detection_enabled

    def unconfident_iq_reescalation_interval_exceeded(self) -> bool:
        """
        Indicates if the unconfident image query re-escalation interval has been exceeded.
        If the old image query still has low confidence, and it's been more than
        `unconfident_iq_reescalation_interval` seconds, we pretend we have motion.
        This is to force the cloud to "think harder" about images which the customer is still seeing,
        for which we still haven't gotten to a confident response.
        """

        if self._previous_motion_detection_time is not None:
            current_time = time.monotonic()
            if current_time - self._previous_motion_detection_time > self._unconfident_iq_reescalation_interval:
                self._previous_motion_detection_time = current_time
                logger.debug("Unconfident image query re-escalation interval exceeded")
                return True

        return False

    def enable(self) -> None:
        if not self._motion_detection_enabled:
            self._motion_detection_enabled = True

    def motion_detected(self, new_img: np.ndarray) -> bool:
        if self._previous_motion_detection_time is not None:
            current_time = time.monotonic()
            if current_time - self._previous_motion_detection_time > self._max_time_between_images:
                self._previous_motion_detection_time = current_time
                logger.debug("Maximum time between cloud-submitted images exceeded")
                return True

        motion_is_detected = self._motion_detector.motion_detected(new_img)
        if motion_is_detected:
            logger.debug("Motion detected")
            self._previous_motion_detection_time = time.monotonic()
        return motion_is_detected


class MotionDetectionManager:
    def __init__(self, config: Dict[str, MotionDetectionConfig]) -> None:
        """
        Initializes the motion detection manager.
        Args:
            config: Dictionary of detector IDs to `MotionDetectionConfig` objects
            `MotionDetectionConfig` objects consist of different parameters needed
            to run motion detection.
        """
        self.detectors = {
            detector_id: MotionDetectorWrapper(parameters=motion_detection_config)
            for detector_id, motion_detection_config in config.items()
        }

    def motion_detection_is_available(self, detector_id: str) -> bool:
        """
        Returns True if motion detection is enabled for the specified detector, False otherwise.
        """
        if detector_id not in self.detectors.keys() or not self.detectors[detector_id].is_enabled():
            logger.debug(f"Motion detection is not enabled for {detector_id=}.")
            return False
        return True

    def update_image_query_response(self, detector_id: str, response: ImageQuery) -> None:
        self.detectors[detector_id].image_query_response = response

    def get_image_query_response(self, detector_id: str) -> Optional[ImageQuery]:
        return self.detectors[detector_id].image_query_response

    def run_motion_detection(self, detector_id: str, new_img: np.ndarray) -> bool:
        """
        Determine if motion is detected for this detector on the given image.
        Args:
            detector_id: ID of the detector to run motion detection on.
            image: Image to run motion detection on.

        Returns:
            True if motion was detected, False otherwise.
        """

        if detector_id not in self.detectors.keys():
            raise ValueError(f"Detector ID {detector_id} not found")

        logger.info(f"Running motion detection for {detector_id=}")
        return self.detectors[detector_id].motion_detected(new_img=new_img)
