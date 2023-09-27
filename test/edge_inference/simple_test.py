
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
    gl = Groundlight()
    detector = DETECTORS["dog_detector"]["detector_id"]
    
    image = Image.open("test/assets/dog.jpeg")
    image_query = gl.submit_image_query(detector=detector, image=image)

    image_query = gl.submit_image_query(detector=detector, image=image)
    # assert image_query.id.startswith("iqe_")


if __name__ == "__main__":
    main()