import argparse

from groundlight import Groundlight
from model import Detector

# TODO: read port from environment variable
gl = Groundlight(endpoint="http://localhost:30107")


def main():
    parser = argparse.ArgumentParser(description="Submit a dog and cat image to k3s Groundlight edge-endpoint for integration tests")
    parser.add_argument("-n", "--num_images", type=int, help="Number of images to submit of each", required=True)
    parser.add_argument("-d", "--detector_id", type=str, help="Id of detector to use. If not provided, we will create a new one", required=False)
    args = parser.parse_args()

    num_images = args.num_images
    detector_id = args.detector_id

    if not detector_id:
        detector = gl.get_or_create_detector(name="cat", query="Is this a cat?")
    else:
        detector = gl.get_detector(detector_id)

    for _ in range(num_images):
        submit_cat(detector)
        submit_dog(detector)


def submit_cat(detector: Detector):
    submit_dog_or_cat(detector, "./test/integration/cat.jpg")

def submit_dog(detector: Detector):
    submit_dog_or_cat(detector, "./test/integration/dog.jpg")

def read_image(img_file):
    with open(img_file, "rb") as img_file:
        byte_stream = img_file.read()
    return byte_stream

def submit_dog_or_cat(detector: Detector, img_file: str):
    image = read_image(img_file)
    gl.submit_image_query(detector=detector, image=image)


if __name__ == "__main__":
    main()
