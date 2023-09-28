import logging
import time

from groundlight import Groundlight
from PIL import Image

DETECTORS = {
    "dog_detector": {
        "detector_id": "det_2UOxalD1gegjk4TnyLbtGggiJ8p",
        "query": "Is there a dog in the image?",
        "confidence_threshold": 0.9,
    },
    "cat_detector": {
        "detector_id": "det_2UOxao4HZyB9gv4ZVtwMOvdqgh9",
        "query": "Is there a cat in the image?",
        "confidence_threshold": 0.9,
    },
}


def main():
    gl = Groundlight(endpoint="http://10.45.0.71:30101")
    detector = DETECTORS["dog_detector"]["detector_id"]

    logging.info(f"detector: {detector}")
    image = Image.open("test/assets/dog.jpeg")

    for _ in range(100):
        image_query = gl.submit_image_query(detector=detector, image=image)

        logging.debug(f"image_query: {image_query}")

        image_query = gl.submit_image_query(detector=detector, image=image)
        time.sleep(1)
        # assert image_query.id.startswith("iqe_")


if __name__ == "__main__":
    logging.basicConfig(level="DEBUG")
    main()
