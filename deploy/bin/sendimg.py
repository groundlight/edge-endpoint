#!/usr/bin/env python3

import argparse
import random
from io import BytesIO

import requests
from groundlight import Groundlight
from PIL import Image

"""
Usage Instructions:
-------------------
This script submits an image to a Groundlight edge-endpoint for analysis.

Options:
-d, --detector_id   : The detector ID to use for submitting the image. (Required)
-i, --image         : The URL of the image to submit. If not provided, a random image will be generated.

Example Usage:
--------------
1. Submit a specific image:
    ./sendimg.py -d <detector_id> -i <image_url>

2. Submit a randomly generated image:
    ./sendimg.py -d <detector_id>

Note:
-----
Ensure that the Groundlight edge-endpoint is running locally on http://localhost:30101.
"""


def generate_random_image(width=224, height=224):
    """Generate a random image with the specified width and height."""
    image = Image.new("RGB", (width, height), (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)))
    return image


def submit_image_to_local_edge_endpoint(image, detector_id):
    buffered = BytesIO()
    image.save(buffered, format="JPEG")
    image_bytes = buffered.getvalue()

    client = Groundlight(endpoint="http://localhost:30101")

    detector = client.get_detector(detector_id)
    response = client.ask_ml(detector=detector, image=image_bytes)
    return response


def main():
    parser = argparse.ArgumentParser(description="Submit an image to a Groundlight edge-endpoint running locally.")
    parser.add_argument("-d", "--detector_id", type=str, help="The detector ID to use for submitting the image.")
    parser.add_argument("-i", "--image", type=str, help="The URL of the image to submit.", required=False)
    args = parser.parse_args()

    if args.image:
        response = requests.get(args.image)
        image = Image.open(BytesIO(response.content))
    else:
        image = generate_random_image()

    response = submit_image_to_local_edge_endpoint(image, args.detector_id)
    print("Response from Groundlight:", response)


if __name__ == "__main__":
    main()
