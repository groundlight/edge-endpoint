# This file contains config variables used by load_test.py and parse_load_test_logs.py.

ENDPOINT_URL = ""  # The URL of the edge endpoint to submit queries to.
DETECTOR_IDS = []  # The id(s) of the detector to submit queries to. If there are multiple, client processes will be split evenly among them as best as possible.
NUM_OBJECTS_EXPECTED = None  # If using a Binary detector, this should be None. If using a Count detector, this should be the number of objects expected to be detected in each image.
IMAGE_PATH = "./images/dog_resized_256x256.jpeg"  # The path to the image that the client processes will submit.
LOG_FILE = "./logs/load_test_log.txt"  # The log file that the client processes will output logs to.
TIME_BETWEEN_RAMP = 30  # The amount of time (in seconds) that each step in the ramp schedule will run for.
REQUESTS_PER_SECOND = 10  # The rate of requests that each client process will attempt to submit.
