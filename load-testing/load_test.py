import argparse
import multiprocessing
import os
import sys
import time

from groundlight import Groundlight

ENDPOINT_URL = os.getenv("ENDPOINT_URL")
if ENDPOINT_URL is None:
    raise OSError("The ENDPOINT_URL environment variable is not set. Please set it and try again.")

# Define constants
DETECTOR_NAME = "edge_test_cat"
DETECTOR_QUERY = "Is there a cat?"
IMAGE_PATH = "./images/resized_dog.jpeg"  # The resized dog is 256x256
REQUESTS_PER_SECOND = 10  # Number of requests per second per process
NUM_PROCESSES = 60  # Number of processes
LOG_DIR = "./logs"  # Directory to store logs
MAIN_PROCESS_STATUS_INTERVAL = 20  # Main process status interval in seconds
DELAY_PER_PROCESS = 0  # How long to stagger each process start time, in seconds


def send_image_requests(process_id, detector, num_requests_per_second, duration, start_delay):
    log_file = os.path.join(LOG_DIR, f"process_{process_id}.log")
    error_log_dir = os.path.join(LOG_DIR, "errors")
    error_log_file = os.path.join(error_log_dir, f"process_{process_id}_errors.log")

    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(error_log_dir, exist_ok=True)

    # Redirect stderr to an error log file to suppress errors in the console
    sys.stderr = open(error_log_file, "w")

    time.sleep(start_delay)  # Stagger process start time by the calculated delay
    start_time = time.time()

    with open(log_file, "w") as log:
        while time.time() - start_time < duration:
            request_start_time = time.time()  # Record the start time

            try:
                # Send the image query request
                image_query = gl.ask_ml(detector=detector, image=IMAGE_PATH, wait=5)
                response_time = time.time() - request_start_time
                log.write(
                    f"{time.strftime('%Y-%m-%d %H:%M:%S')} | Request Start: {request_start_time:.4f} | Response Time: {response_time:.4f} seconds | Result: {image_query.result}\n"
                )
            except Exception as e:
                log.write(
                    f"{time.strftime('%Y-%m-%d %H:%M:%S')} | Request Start: {request_start_time:.4f} | Error: {e} | Process ID: {process_id}\n"
                )

            # Sleep to maintain the desired requests per second
            elapsed_time = time.time() - request_start_time
            time_to_sleep = max(0, (1 / num_requests_per_second) - elapsed_time)
            time.sleep(time_to_sleep)


def initialize_and_start_processes(num_processes, requests_per_second, detector, duration):
    """Starts multiple processes to simulate load testing."""
    # Clear all existing log files before starting the processes
    if os.path.exists(LOG_DIR):
        for log_file in os.listdir(LOG_DIR):
            file_path = os.path.join(LOG_DIR, log_file)
            if os.path.isfile(file_path):
                os.remove(file_path)
    else:
        os.makedirs(LOG_DIR, exist_ok=True)  # Ensure the log directory exists

    processes = []

    # Calculate the delay between each process start
    delay_per_process = DELAY_PER_PROCESS

    for i in range(num_processes):
        start_delay = i * delay_per_process  # Stagger process start time
        process = multiprocessing.Process(
            target=send_image_requests, args=(i, detector, requests_per_second, duration, start_delay)
        )
        processes.append(process)
        process.start()

    # Main process status update loop
    while any(process.is_alive() for process in processes):
        current_time = time.strftime("%Y-%m-%d %H:%M:%S")
        print(
            f"{current_time} | Main process is still running. Active processes: {sum(process.is_alive() for process in processes)} / {num_processes}"
        )
        time.sleep(MAIN_PROCESS_STATUS_INTERVAL)

    # Ensure all processes are running
    for process in processes:
        process.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load test an endpoint by submitting images.")
    parser.add_argument("duration", type=int, help="Number of seconds to run the script")

    args = parser.parse_args()

    gl = Groundlight(endpoint=ENDPOINT_URL)
    detector = gl.get_or_create_detector(name=DETECTOR_NAME, query=DETECTOR_QUERY)

    # Start the load testing processes
    initialize_and_start_processes(NUM_PROCESSES, REQUESTS_PER_SECOND, detector, args.duration)
