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
    dog_detector = DETECTORS["dog_detector"]["detector_id"]
    cat_detector = DETECTORS["cat_detector"]["detector_id"]

    dog_image = Image.open("test/assets/dog.jpeg")
    cat_image = Image.open("test/assets/cat.jpeg")

    for _ in range(100):
        gl.submit_image_query(detector=dog_detector, image=dog_image)

        gl.submit_image_query(detector=cat_detector, image=cat_image)

        time.sleep(1)


if __name__ == "__main__":
    main()
