import argparse
import random

from groundlight import Groundlight
from model import Detector

# TODO: read port from environment variable
gl = Groundlight(endpoint="http://localhost:30107")


def main():
    parser = argparse.ArgumentParser(
        description="Submit a dog and cat image to k3s Groundlight edge-endpoint for integration tests"
    )
    parser.add_argument(
        "-m",
        "--mode",
        type=str,
        choices=["create_detector", "initial", "many", "final"],
        help="Mode of operation: 'initial', 'many', or 'final'",
        required=True,
    )
    parser.add_argument("-d", "--detector_id", type=str, help="id of detector to use", required=False)
    args = parser.parse_args()

    detector = None
    if args.detector_id:
        detector = gl.get_detector(args.detector_id)

    if detector is None and args.mode != "create_detector":
        raise ValueError("You must provide detector id unless mode is create detector")

    if args.mode == "create_detector":
        detector_id = create_cat_detector()
        print(detector_id)  # print so that the shell script can save the value
    elif args.mode == "initial":
        submit_initial(detector)
    elif args.mode == "many":
        submit_many(detector)
    elif args.mode == "final":
        submit_final(detector)


def create_cat_detector() -> str:
    random_number = random.randint(0, 9999)
    detector = gl.create_detector(name=f"cat_{random_number}", query="Is this a cat?")
    detector_id = detector.id
    return detector_id


def submit_initial(detector) -> str:
    result_yes = submit_cat(detector)
    result_no = submit_dog(detector)

    # low confidence before escalating to cloud and pulling new model
    assert result_yes.confidence < 0.6
    assert result_no.confidence < 0.6


def submit_many(detector_id: str):
    gl.get_detector(detector_id)
    pass


def submit_final(detector_id: str):
    pass


def submit_cat(detector: Detector):
    return submit_dog_or_cat(detector, "./test/integration/cat.jpg")


def submit_dog(detector: Detector):
    return submit_dog_or_cat(detector, "./test/integration/dog.jpg")


def read_image(img_file):
    with open(img_file, "rb") as img_file:
        byte_stream = img_file.read()
    return byte_stream


def submit_dog_or_cat(detector: Detector, img_file: str):
    image = read_image(img_file)
    result = gl.submit_image_query(detector=detector, image=image)
    return result


if __name__ == "__main__":
    main()
