import json
import os
import re
from datetime import datetime
from math import ceil, floor

import matplotlib.pyplot as plt
from matplotlib import ticker as mticker
from pydantic import BaseModel


class LoadTestResults(BaseModel):
    start_time: datetime
    average_latency_by_time: dict[datetime, float]
    errors_by_time: dict[datetime, int]
    requests_by_time: dict[datetime, int]
    clients_by_time: dict[datetime, int]
    gpu_by_time: dict[datetime, float]
    cpu_by_time: dict[datetime, float]


class BucketMetrics(BaseModel):
    index: int
    num_clients: int
    total_requests: int
    success_count: int
    duration_sec: float
    achieved_rps: float
    expected_rps: float
    success_rate: float
    latency_p50: float
    latency_p95: float
    is_steady: bool


STEADY_THROUGHPUT_RATIO = 0.99
STEADY_SUCCESS_RATE = 0.99
DEFAULT_MIN_STEADY_DURATION_SEC = 5.0

def parse_log_file(log_file: str) -> LoadTestResults:
    """Parse the log file to gather load test results."""
    start_time = None
    latency_buckets = {}
    error_buckets = {}
    total_request_buckets = {}
    client_buckets = {}
    gpu_buckets = {}
    cpu_buckets = {}

    # Read the log file and extract request start timestamps, response times, and errors
    with open(log_file) as file:
        num_clients = 0
        for line in file:
            if "RAMP" in line:
                num_clients = int(re.search(r"\d+", line).group())
                continue

            log_data = json.loads(line.strip())
            timestamp = datetime.strptime(log_data["asctime"], "%Y-%m-%d %H:%M:%S")
            event_type = log_data.get("event", "request")

            if start_time is None and event_type == "request":
                start_time = timestamp  # Record first request time

            time_bucket = timestamp.replace(microsecond=0)  # Per second granularity

            if event_type == "gpu":
                gpu_buckets.setdefault(time_bucket, [])
                gpu_buckets[time_bucket].append(float(log_data.get("gpu_utilization", 0.0)))
            elif event_type == "request":
                if start_time is None:
                    start_time = timestamp
                # Bucket latencies by second
                latency_buckets.setdefault(time_bucket, [])
                latency_buckets[time_bucket].append(log_data["latency"])

                # Bucketing throughput
                error_buckets.setdefault(time_bucket, 0)
                total_request_buckets.setdefault(time_bucket, 0)
                client_buckets[time_bucket] = num_clients

                total_request_buckets[time_bucket] += 1
                if not log_data["success"]:
                    error_buckets[time_bucket] += 1
            elif event_type == "cpu":
                cpu_buckets.setdefault(time_bucket, [])
                cpu_buckets[time_bucket].append(float(log_data.get("cpu_percent", 0.0)))
            else:
                continue

    # Calculate average latencies for each time bucket
    average_latencies = {bucket: sum(latencies) / len(latencies) for bucket, latencies in latency_buckets.items()}
    average_gpu = {bucket: sum(vals) / len(vals) for bucket, vals in gpu_buckets.items()}
    average_cpu = {bucket: sum(vals) / len(vals) for bucket, vals in cpu_buckets.items()}

    output_dict = {
        "start_time": start_time,
        "average_latency_by_time": average_latencies,
        "errors_by_time": error_buckets,
        "requests_by_time": total_request_buckets,
        "clients_by_time": client_buckets,
        "gpu_by_time": average_gpu,
        "cpu_by_time": average_cpu,
    }
    return LoadTestResults(**output_dict)


def _percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    clamped = min(max(percentile_value, 0.0), 1.0)
    target = clamped * (len(sorted_vals) - 1)
    lower_idx = floor(target)
    upper_idx = ceil(target)
    if lower_idx == upper_idx:
        return sorted_vals[int(target)]
    lower_weight = upper_idx - target
    upper_weight = target - lower_idx
    return (sorted_vals[lower_idx] * lower_weight) + (sorted_vals[upper_idx] * upper_weight)


def calculate_bucket_metrics(
    log_file: str,
    requests_per_second: int,
    bucket_duration_hint_sec: int | None = None,
) -> list[BucketMetrics]:
    """Aggregate per-ramp throughput information."""
    min_steady_duration = DEFAULT_MIN_STEADY_DURATION_SEC
    if bucket_duration_hint_sec:
        min_steady_duration = max(DEFAULT_MIN_STEADY_DURATION_SEC, bucket_duration_hint_sec * 0.5)

    buckets: list[dict] = []
    current_bucket: dict | None = None

    with open(log_file) as file:
        for line in file:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("RAMP"):
                client_match = re.search(r"\d+", stripped)
                if not client_match:
                    continue
                num_clients = int(client_match.group())
                current_bucket = {
                    "index": len(buckets),
                    "num_clients": num_clients,
                    "timestamps": [],
                    "latencies": [],
                    "total_requests": 0,
                    "success_count": 0,
                }
                buckets.append(current_bucket)
                continue

            if stripped.startswith("{"):
                log_data = json.loads(stripped)
            else:
                continue

            if log_data.get("event", "request") != "request":
                continue
            if current_bucket is None:
                continue

            timestamp = datetime.strptime(log_data["asctime"], "%Y-%m-%d %H:%M:%S")
            current_bucket["timestamps"].append(timestamp)
            current_bucket["latencies"].append(float(log_data.get("latency", 0.0)))
            current_bucket["total_requests"] += 1
            if log_data.get("success", False):
                current_bucket["success_count"] += 1

    bucket_metrics: list[BucketMetrics] = []

    for bucket in buckets:
        total_requests = bucket["total_requests"]
        if total_requests == 0:
            continue

        timestamps = bucket["timestamps"]
        start_time = min(timestamps)
        end_time = max(timestamps)
        duration_sec = max((end_time - start_time).total_seconds(), 1e-6)
        achieved_rps = total_requests / duration_sec
        expected_rps = requests_per_second * bucket["num_clients"]
        success_rate = bucket["success_count"] / total_requests if total_requests else 0.0
        latency_p50 = _percentile(bucket["latencies"], 0.5)
        latency_p95 = _percentile(bucket["latencies"], 0.95)

        is_steady = (
            duration_sec >= min_steady_duration
            and expected_rps > 0
            and achieved_rps >= expected_rps * STEADY_THROUGHPUT_RATIO
            and success_rate >= STEADY_SUCCESS_RATE
        )

        bucket_metrics.append(
            BucketMetrics(
                index=bucket["index"],
                num_clients=bucket["num_clients"],
                total_requests=total_requests,
                success_count=bucket["success_count"],
                duration_sec=duration_sec,
                achieved_rps=achieved_rps,
                expected_rps=expected_rps,
                success_rate=success_rate,
                latency_p50=latency_p50,
                latency_p95=latency_p95,
                is_steady=is_steady,
            )
        )

    return bucket_metrics


def plot_throughput_and_system_utilizationby_time(
    load_test_results: LoadTestResults,
    requests_per_second: int,
    output_dir: str,
):
    # Sort the latency data by time
    error_times, error_rate = zip(*sorted(load_test_results.errors_by_time.items()))
    request_times, request_rate = zip(*sorted(load_test_results.requests_by_time.items()))
    client_items = sorted(load_test_results.clients_by_time.items())
    client_times, num_clients = zip(*client_items) if client_items else ([], [])
    expected_response_rate = [requests_per_second * client_count for client_count in num_clients]

    # Calculate elapsed time in seconds
    start_time = load_test_results.start_time
    error_elapsed_seconds = [(time - start_time).total_seconds() for time in error_times]
    request_elapsed_seconds = [(time - start_time).total_seconds() for time in request_times]
    client_elapsed_seconds = [(time - start_time).total_seconds() for time in client_times]
    gpu_items = sorted(load_test_results.gpu_by_time.items())
    cpu_items = sorted(load_test_results.cpu_by_time.items())
    gpu_elapsed_seconds = [(time - start_time).total_seconds() for time, _ in gpu_items]
    gpu_utilization = [value for _, value in gpu_items]
    cpu_elapsed_seconds = [(time - start_time).total_seconds() for time, _ in cpu_items]
    cpu_utilization = [value for _, value in cpu_items]

    # Create the main plot
    fig, ax1 = plt.subplots(figsize=(10, 6))

    # Plot throughput and errors on the main y-axis
    ax1.plot(request_elapsed_seconds, request_rate, linestyle="-", color="green", label="Throughput", alpha=0.9)
    ax1.plot(error_elapsed_seconds, error_rate, linestyle="-", color="red", label="Errors", alpha=0.9)
    ax1.step(
        client_elapsed_seconds,
        expected_response_rate,
        where="post",
        color="black",
        label="Expected Requests / Num Clients",
        alpha=0.9,
    )
    ax1.set_xlabel("Elapsed Time (s)")
    ax1.set_ylabel("Total Requests / Second")
    ax1.grid(True)
    combined_rates = (*request_rate, *error_rate, *expected_response_rate)
    max_expected_requests = max(expected_response_rate) if expected_response_rate else 0
    max_requests = max_expected_requests or (max(combined_rates) if combined_rates else 0)
    ylim_upper = max_requests if max_requests else 1
    ax1.set_ylim((0, ylim_upper))

    # Create system utilization axis for CPU/GPU
    utilization_axis = None
    utilization_lines = []
    if gpu_elapsed_seconds or cpu_elapsed_seconds:
        utilization_axis = ax1.twinx()
        utilization_axis.spines["right"].set_position(("axes", 1.1))
        utilization_axis.set_ylabel("System Utilization (%)")
        utilization_axis.set_ylim(0, 100)
        utilization_axis.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=100, decimals=0))
        utilization_axis.grid(False)
        if gpu_elapsed_seconds:
            (gpu_line,) = utilization_axis.plot(
                gpu_elapsed_seconds,
                gpu_utilization,
                color="orange",
                linestyle=":",
                label="GPU Utilization",
            )
            utilization_lines.append(gpu_line)
        if cpu_elapsed_seconds:
            (cpu_line,) = utilization_axis.plot(
                cpu_elapsed_seconds,
                cpu_utilization,
                color="teal",
                linestyle=":",
                label="CPU Utilization",
            )
            utilization_lines.append(cpu_line)
        utilization_axis.set_xlim(ax1.get_xlim())

    # Create a secondary y-axis for the number of clients aligned to expected request rate
    if requests_per_second > 0:
        client_axis = ax1.secondary_yaxis(
            "right",
            functions=(
                lambda reqs: reqs / requests_per_second,
                lambda clients: clients * requests_per_second,
            ),
        )
    else:
        client_axis = ax1.twinx()
        client_axis.set_ylim(ax1.get_ylim())
    client_axis.set_ylabel("Number of Clients")

    # Set title and save the figure
    plt.title("Throughput and System Utilization Over Time")

    handles, labels = ax1.get_legend_handles_labels()
    if utilization_axis:
        util_handles, util_labels = utilization_axis.get_legend_handles_labels()
        handles.extend(util_handles)
        labels.extend(util_labels)
    ax1.legend(handles, labels, loc="upper left")

    # Save the figure
    ax1.set_xlim(left=0)
    fig.tight_layout()
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, "throughput_and_system_utilization_over_time.png")
    plt.savefig(output_file)

    # Print the file path to the saved plot
    print(f"Plot saved to: {output_file}")


def plot_latency_over_time(
    average_latencies: dict[datetime, float],
    clients: dict[datetime, int],
    start_time: datetime,
    output_dir: str,
):
    """Plot elapsed time vs latency."""
    # Sort the latency data by time
    times, avg_latencies = zip(*sorted(average_latencies.items()))
    client_times, num_clients = zip(*sorted(clients.items()))

    # Calculate elapsed time in seconds
    elapsed_seconds = [(time - start_time).total_seconds() for time in times]
    client_elapsed_seconds = [(time - start_time).total_seconds() for time in client_times]

    # Plot the latency on the main y-axis
    _, ax1 = plt.subplots(figsize=(8, 6))
    ax1.plot(elapsed_seconds, avg_latencies, linestyle="-", label="Latency")
    ax1.set_xlabel("Elapsed Time (seconds)")
    ax1.set_ylabel("Latency (s)")
    ax1.legend(loc="upper left", bbox_to_anchor=(0, 1))
    ax1.grid(True)

    # Create a secondary y-axis for the number of clients
    ax2 = ax1.twinx()
    ax2.plot(client_elapsed_seconds, num_clients, linestyle="-", color="purple", label="# of Clients")
    ax2.set_ylabel("# of Clients")
    ax2.legend(loc="upper left", bbox_to_anchor=(0, 0.92))

    plt.title("Elapsed Time vs Latency")

    # Save the figure
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, "time_vs_latency.png")
    plt.savefig(output_file)

    # Print the file path to the saved plot
    print(f"Plot saved to: {output_file}")


def plot_load_test_results(log_file: str, requests_per_second: int, output_dir: str | None = None):

    resolved_output_dir = output_dir or os.path.dirname(os.path.abspath(log_file))
    load_test_results = parse_log_file(log_file)
    plot_throughput_and_system_utilizationby_time(
        load_test_results,
        requests_per_second=requests_per_second,
        output_dir=resolved_output_dir,
    )
    plot_latency_over_time(
        load_test_results.average_latency_by_time,
        load_test_results.clients_by_time,
        load_test_results.start_time,
        output_dir=resolved_output_dir,
    )
