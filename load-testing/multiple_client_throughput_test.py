import argparse
import json
import multiprocessing
import os
import sys
import time
from datetime import datetime, timezone

from groundlight import ExperimentalApi
from parse_load_test_logs import (
    plot_load_test_results,
    summarize_system_utilization,
    summarize_throughput,
    write_load_test_results_to_file,
)
from tqdm import tqdm

import groundlight_helpers as glh
import image_helpers as imgh
from system_helpers import SystemMonitor



def _collect_run_metadata(
    gl: ExperimentalApi,
    detector,
    image_width: int,
    image_height: int,
) -> dict:
    """Collect per-run metadata for the load test results JSON, derived from the live system and detector."""
    edge_pipeline_config = (glh.get_detector_edge_metrics(gl, detector.id) or {}).get("pipeline_config")
    edge_image, inference_image = glh.get_edge_and_inference_images(gl)
    test_timestamp = datetime.now(timezone.utc).isoformat()

    detector_payload = {
        "detector_id": detector.id,
        "detector_name": detector.name,
        "detector_query": detector.query,
        "mode": detector.mode,
        "cardinality": glh.get_detector_cardinality(detector),
        "edge_pipeline_config": edge_pipeline_config,
    }
    return {
        "test_timestamp": test_timestamp,
        "endpoint": gl.endpoint,
        "edge_endpoint_image": edge_image,
        "inference_server_image": inference_image,
        "image_size": f"{image_width}x{image_height}",
        "detector": detector_payload,
    }


def _create_runtime_directory() -> tuple[str, str]:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    load_tests_dir = os.path.join(script_dir, "load_tests")
    os.makedirs(load_tests_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    runtime_dir = os.path.join(load_tests_dir, timestamp)
    os.makedirs(runtime_dir, exist_ok=True)
    log_file = os.path.join(runtime_dir, "load_test.log")
    return runtime_dir, log_file


def send_image_requests(  # noqa: PLR0913
    process_id: int,
    detector_id: str,
    image_width: int,
    image_height: int,
    num_requests_per_second: float,
    duration: float,
    log_file: str,
):
    """Sends image requests to a Groundlight endpoint for a specified duration and logs results."""
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    sys.stderr = open(os.devnull, "w")

    gl = ExperimentalApi()
    glh.error_if_endpoint_is_cloud(gl)
    detector = gl.get_detector(detector_id)

    start_time = time.time()
    request_number = 1

    while time.time() - start_time < duration:
        request_start_time = time.time()

        try:
            image, _, _ = imgh.generate_random_image(gl, detector, image_width, image_height)
            iq = gl.submit_image_query(detector, image, **glh.IQ_KWARGS_FOR_NO_ESCALATION)
            glh.error_if_not_from_edge(iq)
            success = True
            error = None
        except Exception as e:
            success = False
            error = str(e)

        request_end_time = time.time()
        log_data = {
            "asctime": datetime.fromtimestamp(request_end_time).strftime("%Y-%m-%d %H:%M:%S"),
            "ts": request_end_time,
            "event": "request",
            "worker_number": process_id,
            "request_number": request_number,
            "latency": round(request_end_time - request_start_time, 4),
            "success": success,
        }
        if error is not None:
            log_data["error"] = error

        with open(log_file, "a") as log:
            log.write(json.dumps(log_data) + "\n")

        request_number += 1
        time.sleep(max(0, (1 / num_requests_per_second) - (time.time() - request_start_time)))


def incremental_client_ramp_up(  # noqa: PLR0913
    max_processes: int,
    step_size: int,
    requests_per_second: int,
    detectors: list[str],
    image_width: int,
    image_height: int,
    log_file: str,
    time_between_ramp: int,
):
    """Ramps up the number of client processes over time and distributes them across multiple detectors."""
    if os.path.exists(log_file):
        os.remove(log_file)
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)


    ramp_steps = [step_size * i for i in range(1, round((max_processes / step_size)) + 1)]
    print(
        f"Using step size of {step_size} with {time_between_ramp} seconds between each step. "
        f"Ramp schedule is: {ramp_steps}"
    )

    total_duration = time_between_ramp * len(ramp_steps)
    print(f"Ramping up to {ramp_steps[-1]} clients over a period of {total_duration:.2f} seconds.")

    active_processes = []
    start_time = time.time()
    num_detectors = len(detectors)

    with tqdm(total=total_duration, desc="Running with 0 clients", unit="s") as ramp_progress:
        elapsed_seconds = 0
        for step_idx, num_clients_ramping_to in enumerate(ramp_steps):
            ramp_ts = time.time()
            with open(log_file, "a") as log:
                log.write(f"RAMP {num_clients_ramping_to} ts={ramp_ts}\n")
            num_existing_clients = len(active_processes)
            for _ in range(num_clients_ramping_to - num_existing_clients):
                process_id = len(active_processes)
                remaining_time = total_duration - (time.time() - start_time)
                detector_id = detectors[process_id % num_detectors]

                process = multiprocessing.Process(
                    target=send_image_requests,
                    args=(
                        process_id,
                        detector_id,
                        image_width,
                        image_height,
                        requests_per_second,
                        remaining_time,
                        log_file,
                    ),
                )
                process.start()
                active_processes.append(process)

            ramp_progress.set_description(f"Running with {len(active_processes)} clients")
            seconds_this_step = min(time_between_ramp, max(0, total_duration - elapsed_seconds))
            for second in range(seconds_this_step):
                time.sleep(1)
                elapsed_seconds += 1
                ramp_progress.update(1)
                seconds_remaining_this_step = seconds_this_step - (second + 1)
                ramp_progress.set_postfix_str(
                    f"step {step_idx + 1}/{len(ramp_steps)}, next ramp in {seconds_remaining_this_step}s"
                )

    for process in active_processes:
        process.join()


def main(  # noqa: PLR0913
    detector_mode: str,
    max_clients: int = 10,
    step_size: int = 1,
    time_between_ramp: int = 30,
    requests_per_second: int = 10,
    image_width: int = 640,
    image_height: int = 480,
    edge_pipeline_config: str | None = None,
    cardinality: int | None = None,
) -> None:
    """Provision a detector for the requested mode and run the multi-client throughput ramp."""
    edge_pipeline_config = glh.normalize_edge_pipeline_config(edge_pipeline_config)

    gl = ExperimentalApi()
    glh.error_if_endpoint_is_cloud(gl)
    gl_cloud = ExperimentalApi(endpoint=glh.CLOUD_ENDPOINT_PROD)
    detector = glh.provision_detector(
        gl=gl,
        gl_cloud=gl_cloud,
        detector_mode=detector_mode,
        detector_name_prefix="Throughput Test",
        image_width=image_width,
        image_height=image_height,
        edge_pipeline_config=edge_pipeline_config,
        cardinality=cardinality,
    )

    glh.configure_edge_endpoint(gl, detector)

    runtime_dir, log_file = _create_runtime_directory()
    print(f"Writing load test artifacts to {runtime_dir}.")

    detectors = [detector.id]
    print(f"Running load test for {len(detectors)} detector(s).")

    system_monitor = SystemMonitor(log_file)
    system_monitor.start()
    try:
        incremental_client_ramp_up(
            max_clients,
            step_size,
            requests_per_second,
            detectors,
            image_width,
            image_height,
            log_file,
            time_between_ramp,
        )
    finally:
        system_monitor.stop()

    throughput_summary = summarize_throughput(
        log_file,
        requests_per_second=requests_per_second,
        bucket_duration_hint_sec=time_between_ramp,
    )

    system_utilization_summary = summarize_system_utilization(log_file, throughput_summary.maximum_steady_ramp)

    plot_load_test_results(
        log_file,
        requests_per_second,
        output_dir=runtime_dir,
        steady_rps=throughput_summary.maximum_steady_rps,
    )

    metadata = _collect_run_metadata(gl, detector, image_width, image_height)
    cli_args = argparse.Namespace(
        detector_mode=detector_mode, max_clients=max_clients, step_size=step_size,
        time_between_ramp=time_between_ramp, requests_per_second=requests_per_second,
        image_width=image_width, image_height=image_height, edge_pipeline_config=edge_pipeline_config,
        cardinality=cardinality,
    )
    write_load_test_results_to_file(
        log_file,
        cli_args,
        throughput_summary,
        metadata=metadata,
        system_utilization_summary=system_utilization_summary,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load test an endpoint by submitting generated images.")
    parser.add_argument("detector_mode", choices=glh.SUPPORTED_DETECTOR_MODES, help="Detector mode to test.")
    parser.add_argument("--max-clients", type=int, default=10, help="Number of processes to ramp up to.")
    parser.add_argument("--step-size", type=int, default=1, help="Number of clients to add at each step.")
    parser.add_argument("--time-between-ramp", type=int, default=30, help="Seconds to run each ramp step.")
    parser.add_argument("--requests-per-second", type=int, default=10, help="Per-client request rate.")
    parser.add_argument("--image-width", type=int, default=640)
    parser.add_argument("--image-height", type=int, default=480)
    parser.add_argument("--edge-pipeline-config", type=str, default=None, help="Edge pipeline configuration name.")
    parser.add_argument(
        "--cardinality", type=int, default=None,
        help=(
            "Size of the detector's output/label space. Maps to max_count for COUNT, "
            "max_num_bboxes for BOUNDING_BOX, and num_classes for MULTI_CLASS. "
            "For BINARY only 2 is accepted. "
            "If omitted, a per-mode default is used."
        ),
    )
    args = parser.parse_args()
    main(**vars(args))
