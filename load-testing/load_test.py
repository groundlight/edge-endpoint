import argparse
import json
import multiprocessing
import os
import time
from datetime import datetime

from groundlight import Detector, Groundlight
from parse_load_test_logs import show_load_test_results

ENDPOINT_URL = os.getenv("ENDPOINT_URL")
if not ENDPOINT_URL:
    raise OSError("The ENDPOINT_URL environment variable is not set.")

DETECTOR_NAME = "edge_test_cat"
DETECTOR_QUERY = "Is there a cat?"
IMAGE_PATH = "./images/resized_dog.jpeg"
LOG_FILE = "./logs/load_test_log.txt"
MAIN_PROCESS_STATUS_INTERVAL = 10
TIME_BETWEEN_RAMP = 30
REQUESTS_PER_SECOND = 10


def send_image_requests(
    process_id: int, detector: Detector, gl_client: Groundlight, num_requests_per_second: float, duration, log_file: str
):
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    start_time = time.time()
    request_number = 1

    while time.time() - start_time < duration:
        request_start_time = time.time()

        log_data = {
            "asctime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "worker_number": process_id,
            "request_number": request_number,
        }

        try:
            gl_client.ask_ml(detector=detector, image=IMAGE_PATH, wait=1)
            log_data.update({"latency": round(time.time() - request_start_time, 4), "success": True})
        except Exception as e:
            log_data.update({"latency": round(time.time() - request_start_time, 4), "success": False, "error": str(e)})

        with open(log_file, "a") as log:
            log.write(json.dumps(log_data) + "\n")

        request_number += 1

        time.sleep(max(0, (1 / num_requests_per_second) - (time.time() - request_start_time)))


def initialize_and_start_processes(num_processes, requests_per_second, detector, gl_client, duration):
    """Static mode: Start all processes at once."""
    if os.path.exists(LOG_FILE):
        os.remove(LOG_FILE)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

    processes = []
    for i in range(num_processes):
        process = multiprocessing.Process(
            target=send_image_requests,
            args=(i, detector, gl_client, requests_per_second, duration, LOG_FILE),
        )
        processes.append(process)
        process.start()

    while any(process.is_alive() for process in processes):
        print(
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Active processes: {sum(p.is_alive() for p in processes)} / {num_processes}"
        )
        time.sleep(MAIN_PROCESS_STATUS_INTERVAL)

    for process in processes:
        process.join()


def ramp_up_processes(max_processes, step_size, requests_per_second, detector, gl_client):  # noqa: PLR0913
    """Ramp-up mode: Gradually increase the number of processes that run until the end."""
    if os.path.exists(LOG_FILE):
        os.remove(LOG_FILE)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

    total_duration = TIME_BETWEEN_RAMP * max_processes / step_size
    print(f"Ramping up to {max_processes} in steps of {step_size} over {total_duration:.2f} seconds.")

    active_processes = []
    start_time = time.time()

    for curr_processes in range(step_size, max_processes + 1, step_size):
        with open(LOG_FILE, "a") as log:
            log.write(f"RAMP {curr_processes}\n")
        # Start new processes in increments of step_size
        for _ in range(step_size):
            process_id = len(active_processes)
            remaining_time = total_duration - (time.time() - start_time)
            process = multiprocessing.Process(
                target=send_image_requests,
                args=(
                    process_id,
                    detector,
                    gl_client,
                    requests_per_second,
                    remaining_time,
                    LOG_FILE,
                ),
            )
            process.start()
            active_processes.append(process)

        # Monitor the system and log throughput for the current client count
        print(f"Running with {len(active_processes)} clients...")

        # Allow processes to run for some time before ramping up again
        print(f"Sleeping for {TIME_BETWEEN_RAMP} seconds.")
        time.sleep(TIME_BETWEEN_RAMP)  # Adjust based on the stabilization time needed

    # Ensure all processes finish
    for process in active_processes:
        process.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load test an endpoint by submitting images.")
    # parser.add_argument("duration", type=int, help="Number of seconds to run the script")
    parser.add_argument("--max-clients", type=int, default=10, help="Number of processes to ramp up to")
    parser.add_argument(
        "--mode",
        choices=["static", "ramp-up"],
        default="static",
        help="Choose between static mode (default) or ramp-up mode.",
    )
    parser.add_argument(
        "--step-size", type=int, default=1, help="Number of clients to add at each step in ramp-up mode."
    )
    args = parser.parse_args()

    gl = Groundlight(endpoint=ENDPOINT_URL)
    detector = gl.get_or_create_detector(name=DETECTOR_NAME, query=DETECTOR_QUERY)

    if args.mode == "ramp-up":
        print("Running in ramp-up mode")
        # In ramp-up mode, progressively increase the number of clients
        ramp_up_processes(args.max_clients, args.step_size, REQUESTS_PER_SECOND, detector, gl)
    else:
        print("no static mode right now")
        # print("Running in static mode")
        # # In static mode, start all clients at once
        # initialize_and_start_processes(NUM_PROCESSES, REQUESTS_PER_SECOND, detector, gl, args.duration)

    show_load_test_results()
