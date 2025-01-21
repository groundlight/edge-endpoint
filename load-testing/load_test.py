import argparse
import json
import multiprocessing
import os
import sys
import time
from datetime import datetime

from config import (
    DETECTOR_IDS,
    ENDPOINT_URL,
    IMAGE_PATH,
    LOG_FILE,
    NUM_OBJECTS_EXPECTED,
    REQUESTS_PER_SECOND,
    TIME_BETWEEN_RAMP,
)
from groundlight import Detector, Groundlight
from parse_load_test_logs import show_load_test_results

if ENDPOINT_URL == "":
    raise ValueError("ENDPOINT_URL cannot be an empty string.")


def send_image_requests(  # noqa: PLR0913
    process_id: int,
    detector: Detector,
    gl_client: Groundlight,
    num_requests_per_second: float,
    duration: float,
    log_file: str,
):
    """Sends image requests to a Groundlight endpoint for a specified duration and logs results."""
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    # Prevent errors from appearing in terminal
    sys.stderr = open(os.devnull, "w")

    start_time = time.time()
    request_number = 1

    while time.time() - start_time < duration:
        log_data = {
            "asctime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "worker_number": process_id,
            "request_number": request_number,
        }
        request_start_time = time.time()

        try:
            answer = gl_client.ask_ml(detector=detector, image=IMAGE_PATH, wait=1)
            if NUM_OBJECTS_EXPECTED is not None and answer.result.count != NUM_OBJECTS_EXPECTED:
                print(f"Error: Expected count {NUM_OBJECTS_EXPECTED}, got {answer.result.count}")
            log_data.update({"latency": round(time.time() - request_start_time, 4), "success": True})
        except Exception as e:
            log_data.update({"latency": round(time.time() - request_start_time, 4), "success": False, "error": str(e)})

        with open(log_file, "a") as log:
            log.write(json.dumps(log_data) + "\n")

        request_number += 1

        time.sleep(max(0, (1 / num_requests_per_second) - (time.time() - request_start_time)))


def incremental_client_ramp_up(  # noqa: PLR0913
    max_processes: int,
    step_size: int,
    requests_per_second: int,
    detectors: list[Detector],
    gl_client: Groundlight,
    use_preset_schedule: bool = False,
):
    """Ramps up the number of client processes over time and distributes them across multiple detectors."""
    if os.path.exists(LOG_FILE):
        os.remove(LOG_FILE)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

    if use_preset_schedule:
        ramp_steps = [1, 2, 3, 4, 5, 10, 15, 20, 30, 40, 50, 60]
        print(f"Using preset ramp schedule: {ramp_steps} with {TIME_BETWEEN_RAMP} seconds between each step.")
    else:
        ramp_steps = [step_size * i for i in range(1, round((max_processes / step_size)) + 1)]
        print(
            f"Using step size of {step_size} with {TIME_BETWEEN_RAMP} seconds between each step. "
            f"Ramp schedule is: {ramp_steps}"
        )

    total_duration = TIME_BETWEEN_RAMP * len(ramp_steps)
    print(f"Ramping up to {ramp_steps[-1]} over {total_duration:.2f} seconds.")

    active_processes = []
    start_time = time.time()
    num_detectors = len(detectors)

    for num_clients_ramping_to in ramp_steps:
        print(f"Ramping up to {num_clients_ramping_to} clients.")
        with open(LOG_FILE, "a") as log:
            log.write(f"RAMP {num_clients_ramping_to}\n")
        # Start new processes in incremental steps
        num_existing_clients = len(active_processes)
        for _ in range(num_clients_ramping_to - num_existing_clients):
            process_id = len(active_processes)
            remaining_time = total_duration - (time.time() - start_time)
            # Distribute clients across detectors
            detector = detectors[process_id % num_detectors]

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

        print(f"Running with {len(active_processes)} clients...")

        # Allow processes to run for some time before ramping up again
        print(f"Sleeping for {TIME_BETWEEN_RAMP} seconds.")
        time.sleep(TIME_BETWEEN_RAMP)

    # Ensure all processes finish
    for process in active_processes:
        process.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load test an endpoint by submitting images.")
    parser.add_argument("--max-clients", type=int, default=10, help="Number of processes to ramp up to")
    parser.add_argument(
        "--step-size", type=int, default=1, help="Number of clients to add at each step in ramp-up mode."
    )
    parser.add_argument("--use-preset-schedule", action="store_true", help="Enable using a preset schedule.")
    args = parser.parse_args()

    gl = Groundlight(endpoint=ENDPOINT_URL)

    # Fetch detectors ahead of time
    detectors = [gl.get_detector(id=detector_id) for detector_id in DETECTOR_IDS]
    if len(detectors) == 0:
        raise ValueError("At least one detector must be specified in the config.")
    print(f"Running load test for {len(detectors)} detector(s).")

    if args.use_preset_schedule:
        print("Using preset schedule. Step size and max clients will be ignored.")

    incremental_client_ramp_up(
        args.max_clients, args.step_size, REQUESTS_PER_SECOND, detectors, gl, args.use_preset_schedule
    )

    show_load_test_results()
