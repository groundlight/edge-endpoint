import argparse
import random

from groundlight import Groundlight, GroundlightClientError
from model import Detector

NUM_IQS_TO_IMPROVE_MODEL = 20


def get_groundlight():
    try:
        return Groundlight(endpoint="http://localhost:30107")
    except GroundlightClientError:
        # we use this to create a detector since we do that before setting up edge
        # although maybe we want to be more careful here about making sure that's
        # the case we're in
        return Groundlight()


gl = get_groundlight()


def main():
    parser = argparse.ArgumentParser(
        description="Submit a dog and cat image to k3s Groundlight edge-endpoint for integration tests"
    )
    parser.add_argument(
        "-m",
        "--mode",
        type=str,
        choices=["create_detector", "initial", "improve_model", "final"],
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
    elif args.mode == "improve_model":
        improve_model(detector)
    elif args.mode == "final":
        submit_final(detector)


def create_cat_detector() -> str:
    random_number = random.randint(0, 9999)
    detector = gl.create_detector(name=f"cat_{random_number}", query="Is this a cat?")
    detector_id = detector.id
    return detector_id


def submit_initial(detector) -> str:
    # 0.5 threshold to ensure we get a edge answer
    iq_yes = submit_cat(detector, confidence_threshold=0.5)
    iq_no = submit_dog(detector, confidence_threshold=0.5)

    # a bit dependent on the current default model,
    # but that one always defaults to 0.5 confidence at first.
    assert iq_yes.result.confidence == 0.5
    assert iq_no.result.confidence == 0.5


def improve_model(detector):
    for _ in range(NUM_IQS_TO_IMPROVE_MODEL):
        # there's a subtle tradeoff here.
        # we're submitting images from the edge which will get escalated to the cloud
        # and thus train our model. but this process is slow
        iq_yes = submit_cat(detector, confidence_threshold=1, wait=0)
        gl.add_label(image_query=iq_yes, label="YES")
        iq_no = submit_dog(detector, confidence_threshold=1, wait=0)
        gl.add_label(image_query=iq_no, label="NO")


def submit_final(detector_id: str):
    pass


def submit_cat(detector: Detector, confidence_threshold: float, wait: int = None):
    return submit_dog_or_cat(
        detector=detector, confidence_threshold=confidence_threshold, img_file="./test/integration/cat.jpg", wait=wait
    )


def submit_dog(detector: Detector, confidence_threshold: float, wait: int = None):
    return submit_dog_or_cat(
        detector=detector, confidence_threshold=confidence_threshold, img_file="./test/integration/dog.jpg", wait=wait
    )


def read_image(img_file):
    with open(img_file, "rb") as img_file:
        byte_stream = img_file.read()
    return byte_stream


def submit_dog_or_cat(detector: Detector, confidence_threshold: float, img_file: str, wait: int = None):
    read_image(img_file)

    image_query = gl.submit_image_query(
        detector=detector, confidence_threshold=confidence_threshold, image=img_file, wait=wait
    )

    return image_query


if __name__ == "__main__":
    main()
