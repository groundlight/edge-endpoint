# This file contains config variables used by load_test.py and parse_load_test_logs.py.

ENDPOINT_URL = "http://10.57.10.150:30103"  # The URL of the edge endpoint to submit queries to.
DETECTOR_NAME = "edge_test_cat"  # The name of the detector to submit queries to.
DETECTOR_QUERY = "Is there a cat?"  # The query of the detector to submit queries to.
IMAGE_PATH = "./images/resized_dog.jpeg"  # The path to the image that the client processes will submit.
LOG_FILE = "./logs/load_test_log.txt"  # The log file that the client processes will output logs to.
TIME_BETWEEN_RAMP = 30  # The amount of time that each step in the ramp schedule will run for.
REQUESTS_PER_SECOND = 10  # The rate of requests that each client process will attempt to submit.
