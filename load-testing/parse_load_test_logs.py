import json
import os
import re
from datetime import datetime

import matplotlib.pyplot as plt
from pydantic import BaseModel


class LoadTestResults(BaseModel):
    start_time: datetime
    average_latency_by_time: dict[datetime, float]
    successes_by_time: dict[datetime, int]
    errors_by_time: dict[datetime, int]
    requests_by_time: dict[datetime, int]
    clients_by_time: dict[datetime, int]
    gpu_by_time: dict[datetime, float]


def parse_log_file(log_file: str) -> LoadTestResults:
    """Parse the log file to gather load test results."""
    start_time = None
    latency_buckets = {}
    success_buckets = {}
    error_buckets = {}
    total_request_buckets = {}
    client_buckets = {}
    gpu_buckets = {}

    # Read the log file and extract request start timestamps, response times, and errors
    with open(log_file) as file:
        num_clients = 0
        for line in file:
            if "RAMP" in line:
                num_clients = int(re.search(r"\d+", line).group())
            else:
                log_data = json.loads(line.strip())
                timestamp = datetime.strptime(log_data["asctime"], "%Y-%m-%d %H:%M:%S")
                event_type = log_data.get("event", "request")

                if start_time is None:
                    start_time = timestamp  # Record first request time

                time_bucket = timestamp.replace(microsecond=0)  # Per second granularity

                if event_type == "gpu":
                    gpu_buckets.setdefault(time_bucket, [])
                    gpu_buckets[time_bucket].append(float(log_data.get("gpu_utilization", 0.0)))
                else:
                    # Bucket latencies by second
                    latency_buckets.setdefault(time_bucket, [])
                    latency_buckets[time_bucket].append(log_data["latency"])

                    # Bucketing throughput
                    success_buckets.setdefault(time_bucket, 0)
                    error_buckets.setdefault(time_bucket, 0)
                    total_request_buckets.setdefault(time_bucket, 0)
                    client_buckets.setdefault(time_bucket, num_clients)

                    total_request_buckets[time_bucket] += 1
                    if not log_data["success"]:
                        error_buckets[time_bucket] += 1
                    else:
                        success_buckets[time_bucket] += 1

    # Calculate average latencies for each time bucket
    average_latencies = {bucket: sum(latencies) / len(latencies) for bucket, latencies in latency_buckets.items()}
    average_gpu = {bucket: sum(vals) / len(vals) for bucket, vals in gpu_buckets.items()}

    output_dict = {
        "start_time": start_time,
        "average_latency_by_time": average_latencies,
        "successes_by_time": success_buckets,
        "errors_by_time": error_buckets,
        "requests_by_time": total_request_buckets,
        "clients_by_time": client_buckets,
        "gpu_by_time": average_gpu,
    }
    return LoadTestResults(**output_dict)


def plot_throughput_by_time(
    load_test_results: LoadTestResults,
    requests_per_second: int,
    output_dir: str = "./plots",
):
    """Plot elapsed time vs throughput, success rate, and error rate."""
    # Sort the latency data by time
    success_times, success_rate = zip(*sorted(load_test_results.successes_by_time.items()))
    error_times, error_rate = zip(*sorted(load_test_results.errors_by_time.items()))
    request_times, request_rate = zip(*sorted(load_test_results.requests_by_time.items()))
    client_times, num_clients = zip(*sorted(load_test_results.clients_by_time.items()))
    expected_response_rate = [requests_per_second * client_count for client_count in num_clients]

    # Calculate elapsed time in seconds
    start_time = load_test_results.start_time
    success_elapsed_seconds = [(time - start_time).total_seconds() for time in success_times]
    error_elapsed_seconds = [(time - start_time).total_seconds() for time in error_times]
    request_elapsed_seconds = [(time - start_time).total_seconds() for time in request_times]
    client_elapsed_seconds = [(time - start_time).total_seconds() for time in client_times]

    # Create the main plot
    fig, ax1 = plt.subplots(figsize=(8, 6))

    # Plot throughput, successes, and errors on the main y-axis
    ax1.plot(request_elapsed_seconds, request_rate, linestyle="-", label="Throughput", alpha=0.8)
    ax1.plot(success_elapsed_seconds, success_rate, linestyle="--", label="Successes", alpha=0.8)
    ax1.plot(error_elapsed_seconds, error_rate, linestyle="-", label="Errors", alpha=0.8)
    ax1.plot(client_elapsed_seconds, expected_response_rate, linestyle="-", label="Expected Requests", alpha=0.8)
    ax1.set_xlabel("Elapsed Time (s)")
    ax1.set_ylabel("Requests / Second")
    ax1.grid(True)
    ax1.legend(loc="upper left")
    # Set a fixed y-axis limit to avoid it adjusting based on the expected response rate
    ax1.set_ylim((0, max(*request_rate, *success_rate, *error_rate) * 1.4))

    # Create a secondary y-axis for the number of clients
    ax2 = ax1.twinx()
    ax2.plot(client_elapsed_seconds, num_clients, linestyle="-", color="purple", label="# of Clients", alpha=1)
    ax2.set_ylabel("Number of Clients")
    ax2.legend(loc="upper right")

    # Set title and save the figure
    plt.title("Elapsed Time vs Throughput, Successes, Errors, and Clients")

    # Save the figure
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, "time_vs_throughput.png")
    plt.savefig(output_file)

    # Print the file path to the saved plot
    print(f"Plot saved to: {output_file}")


def plot_latency_over_time(
    average_latencies: dict[datetime, float],
    clients: dict[datetime, int],
    start_time: datetime,
    output_dir: str = "./plots",
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


def plot_gpu_over_time(
    gpu_by_time: dict[datetime, float],
    clients: dict[datetime, int],
    start_time: datetime,
    output_dir: str = "./plots",
):
    """Plot elapsed time vs GPU utilization with clients overlay."""
    if not gpu_by_time:
        return
    # Sort the data by time
    times, gpu_util = zip(*sorted(gpu_by_time.items()))
    client_times, num_clients = zip(*sorted(clients.items())) if clients else ([], [])

    # Calculate elapsed time in seconds
    elapsed_seconds = [(time - start_time).total_seconds() for time in times]
    client_elapsed_seconds = [(time - start_time).total_seconds() for time in client_times] if client_times else []

    # Plot the GPU utilization on the main y-axis
    _, ax1 = plt.subplots(figsize=(8, 6))
    ax1.plot(elapsed_seconds, gpu_util, linestyle="-", color="green", label="GPU Utilization (%)")
    ax1.set_xlabel("Elapsed Time (seconds)")
    ax1.set_ylabel("GPU Utilization (%)")
    ax1.set_ylim(0, 100)
    ax1.legend(loc="upper left", bbox_to_anchor=(0, 1))
    ax1.grid(True)

    # Create a secondary y-axis for the number of clients
    if client_elapsed_seconds:
        ax2 = ax1.twinx()
        ax2.plot(client_elapsed_seconds, num_clients, linestyle="-", color="purple", label="# of Clients")
        ax2.set_ylabel("# of Clients")
        ax2.legend(loc="upper left", bbox_to_anchor=(0, 0.92))

    plt.title("Elapsed Time vs GPU Utilization")

    # Save the figure
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, "time_vs_gpu.png")
    plt.savefig(output_file)

    # Print the file path to the saved plot
    print(f"Plot saved to: {output_file}")


def show_load_test_results(log_file: str, requests_per_second: int):
    if not os.path.exists(log_file):
        print(f"Log file {log_file} not found.")
        return
    load_test_results = parse_log_file(log_file)
    plot_throughput_by_time(load_test_results, requests_per_second=requests_per_second)
    plot_latency_over_time(
        load_test_results.average_latency_by_time, load_test_results.clients_by_time, load_test_results.start_time
    )
    plot_gpu_over_time(
        load_test_results.gpu_by_time, load_test_results.clients_by_time, load_test_results.start_time
    )
