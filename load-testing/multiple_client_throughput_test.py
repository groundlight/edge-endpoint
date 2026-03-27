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

SUPPORTED_DETECTOR_MODES = {"BINARY", "COUNT"}
DETECTOR_GROUP_NAME = "Load Testing"


def _collect_run_metadata(
    gl: ExperimentalApi,
    detector,
    detector_mode: str,
    image_width: int,
    image_height: int,
) -> dict:
    edge_pipeline_config = (glh.get_detector_edge_metrics(gl, detector.id) or {}).get("pipeline_config")
    edge_image, inference_image = glh.get_edge_and_inference_images(gl)
    test_timestamp = datetime.now(timezone.utc).isoformat()

    detector_payload = {
        "detector_id": detector.id,
        "detector_name": detector.name,
        "detector_query": detector.query,
        "pipeline_config": edge_pipeline_config,
    }
    return {
        "test_timestamp": test_timestamp,
        "endpoint": gl.endpoint,
        "edge_endpoint_image": edge_image,
        "inference_server_image": inference_image,
        "image_size": f"{image_width}x{image_height}",
        "detector_mode": detector_mode,
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


def _provision_detector(
    gl: ExperimentalApi,
    gl_cloud: ExperimentalApi,
    detector_mode: str,
    image_width: int,
    image_height: int,
    edge_pipeline_config: str | None = None,
):
    TRAINING_TIMEOUT_SEC = 60 * 20
    INFERENCE_POD_READY_TIMEOUT_SEC = 60 * 10

    detector_name = f"Throughput Test {image_width} x {image_height} - {detector_mode}"
    if edge_pipeline_config is not None:
        config_hash = glh.hash_pipeline_config(edge_pipeline_config)
        detector_name += f" - {config_hash}"

    if detector_mode == "BINARY":
        detector = gl.get_or_create_detector(
            name=detector_name,
            query="Is the image background black?",
            group_name=DETECTOR_GROUP_NAME,
            edge_pipeline_config=edge_pipeline_config,
        )
        generate_image = imgh.generate_random_binary_image
        generate_image_kwargs = {
            "gl": gl,
            "image_width": image_width,
            "image_height": image_height,
        }
    elif detector_mode == "COUNT":
        class_name = "circle"
        max_count = 10
        detector = glh.get_or_create_count_detector(
            gl,
            name=detector_name,
            class_name=class_name,
            max_count=max_count,
            group_name=DETECTOR_GROUP_NAME,
            edge_pipeline_config=edge_pipeline_config,
        )
        generate_image = imgh.generate_random_count_image
        generate_image_kwargs = {
            "gl": gl,
            "image_width": image_width,
            "image_height": image_height,
            "class_name": class_name,
            "max_count": max_count,
        }
    else:
        raise ValueError(f"Detector mode {detector_mode} not recognized.")

    if edge_pipeline_config is not None:
        glh.assert_configured_edge_pipeline_matches_provided(gl, detector.id, edge_pipeline_config)

    stats = glh.get_detector_evaluation(gl, detector.id)
    if not glh.detector_is_sufficiently_trained(stats, 0.6, 30):
        print(
            f"{detector.id} is not sufficiently trained yet "
            f"(projected_ml_accuracy={stats.get('projected_ml_accuracy')}, total_labels={stats.get('total_labels')}; "
            "need projected_ml_accuracy>0.6 and total_labels>=30). Priming with 30 labels."
        )
        glh.prime_detector(gl_cloud, detector, 30, image_width, image_height)
        print(f"Waiting up to {TRAINING_TIMEOUT_SEC} seconds for training to complete for {detector.id}...")
        glh.wait_until_sufficiently_trained(gl, detector, 0.6, 30, timeout_sec=TRAINING_TIMEOUT_SEC)

    print(f'Waiting for inference pod to be ready for {detector.id}...')
    glh.wait_for_ready_inference_pod(
        gl, detector, image_width, image_height,
        timeout_sec=INFERENCE_POD_READY_TIMEOUT_SEC,
        edge_pipeline_config=edge_pipeline_config,
    )
    loaded_pipeline_config = (glh.get_detector_edge_metrics(gl, detector.id) or {}).get("pipeline_config")
    print(f"Inference pod ready for {detector.id} with pipeline '{loaded_pipeline_config}'.")

    return detector, generate_image, generate_image_kwargs


def send_image_requests(  # noqa: PLR0913
    process_id: int,
    detector_id: str,
    detector_mode: str,
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

    if detector_mode == "BINARY":
        generate_image = imgh.generate_random_binary_image
        generate_image_kwargs = {
            "gl": gl,
            "image_width": image_width,
            "image_height": image_height,
        }
    else:
        generate_image = imgh.generate_random_count_image
        generate_image_kwargs = {
            "gl": gl,
            "image_width": image_width,
            "image_height": image_height,
            "class_name": "circle",
            "max_count": 10,
        }

    start_time = time.time()
    request_number = 1

    while time.time() - start_time < duration:
        request_start_time = time.time()

        try:
            image, _, _ = generate_image(**generate_image_kwargs)
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
    detector_mode: str,
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
                        detector_mode,
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load test an endpoint by submitting generated images.")
    parser.add_argument("detector_mode", choices=SUPPORTED_DETECTOR_MODES, help="Detector mode to test.")
    parser.add_argument("--max-clients", type=int, default=10, help="Number of processes to ramp up to.")
    parser.add_argument("--step-size", type=int, default=1, help="Number of clients to add at each step.")
    parser.add_argument("--time-between-ramp", type=int, default=30, help="Seconds to run each ramp step.")
    parser.add_argument("--requests-per-second", type=int, default=10, help="Per-client request rate.")
    parser.add_argument("--image-width", type=int, default=640)
    parser.add_argument("--image-height", type=int, default=480)
    parser.add_argument("--edge-pipeline-config", type=str, default=None, help="Edge pipeline configuration name.")
    args = parser.parse_args()
    edge_pipeline_config = glh.normalize_edge_pipeline_config(args.edge_pipeline_config)

    gl = ExperimentalApi()
    glh.error_if_endpoint_is_cloud(gl)
    gl_cloud = ExperimentalApi(endpoint=glh.CLOUD_ENDPOINT_PROD)

    detector, generate_image, generate_image_kwargs = _provision_detector(
        gl, gl_cloud, args.detector_mode, args.image_width, args.image_height, edge_pipeline_config=edge_pipeline_config
    )

    runtime_dir, log_file = _create_runtime_directory()
    print(f"Writing load test artifacts to {runtime_dir}.")

    detectors = [detector.id]
    print(f"Running load test for {len(detectors)} detector(s).")

    system_monitor = SystemMonitor(log_file)
    system_monitor.start()
    try:
        incremental_client_ramp_up(
            args.max_clients,
            args.step_size,
            args.requests_per_second,
            detectors,
            args.detector_mode,
            args.image_width,
            args.image_height,
            log_file,
            args.time_between_ramp,
        )
    finally:
        system_monitor.stop()

    throughput_summary = summarize_throughput(
        log_file,
        requests_per_second=args.requests_per_second,
        bucket_duration_hint_sec=args.time_between_ramp,
    )

    system_utilization_summary = summarize_system_utilization(log_file, throughput_summary.maximum_steady_ramp)

    plot_load_test_results(
        log_file,
        args.requests_per_second,
        output_dir=runtime_dir,
        steady_rps=throughput_summary.maximum_steady_rps,
    )


    metadata = _collect_run_metadata(gl, detector, args.detector_mode, args.image_width, args.image_height)
    write_load_test_results_to_file(
        log_file,
        args,
        throughput_summary,
        metadata=metadata,
        system_utilization_summary=system_utilization_summary,
    )