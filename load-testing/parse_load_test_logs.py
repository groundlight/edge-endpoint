import datetime as dt
import json
import os
import re
from collections import defaultdict
from datetime import datetime
from typing import Any

import matplotlib.pyplot as plt
from pydantic import BaseModel

REQUESTS_PER_SECOND = 10  # TODO this should be synced b/t this file and load_test.py


class LoadTestResults(BaseModel):
    start_time: datetime
    end_time: datetime
    error_count: int
    response_times: list[float]
    average_latency_by_time: dict[datetime, float]
    average_latency_by_clients: dict[int, float]
    successes_by_time: dict[datetime, int]
    errors_by_time: dict[datetime, int]
    requests_by_time: dict[datetime, int]
    clients_by_time: dict[datetime, int]


def parse_log_file(log_file: str) -> LoadTestResults:
    """Parse the log file to gather throughput data for static or ramp-up mode."""
    response_times = []  # To track response times for each request
    error_count = 0
    start_time, end_time = None, None

    latency_buckets = {}
    latency_by_clients = {}  # Track latencies by the number of clients
    success_buckets = {}
    error_buckets = {}
    total_request_buckets = {}
    client_buckets = {}

    # Read the log file and extract request start timestamps, response times, and errors
    with open(log_file) as file:
        num_clients = 0
        for line in file:
            if "RAMP" in line:
                num_clients = int(re.search(r"\d+", line).group())
            else:
                log_data = json.loads(line.strip())
                timestamp = datetime.strptime(log_data["asctime"], "%Y-%m-%d %H:%M:%S")

                if start_time is None:
                    start_time = timestamp  # Record first request time
                end_time = timestamp  # Continuously update last request time

                if not log_data["success"]:
                    error_count += 1
                response_times.append(log_data["latency"])

                # Bucket latencies by second
                time_bucket = timestamp.replace(microsecond=0)  # Per second granularity
                if time_bucket not in latency_buckets:
                    latency_buckets[time_bucket] = []
                latency_buckets[time_bucket].append(log_data["latency"])

                # Bucketing throughput
                if time_bucket not in success_buckets:
                    success_buckets[time_bucket] = 0
                if time_bucket not in error_buckets:
                    error_buckets[time_bucket] = 0
                if time_bucket not in total_request_buckets:
                    total_request_buckets[time_bucket] = 0
                if not log_data["success"]:
                    error_buckets[time_bucket] += 1
                else:
                    success_buckets[time_bucket] += 1
                total_request_buckets[time_bucket] += 1

                if time_bucket not in client_buckets:
                    client_buckets[time_bucket] = num_clients

                # Track latencies by the number of clients
                if num_clients not in latency_by_clients:
                    latency_by_clients[num_clients] = []

                latency_by_clients[num_clients].append(log_data["latency"])

    # Calculate average latencies for each time bucket
    average_latencies = {bucket: sum(latencies) / len(latencies) for bucket, latencies in latency_buckets.items()}

    # Calculate average latencies for each client count
    average_latency_by_clients = {
        clients: sum(latencies) / len(latencies) for clients, latencies in latency_by_clients.items()
    }

    output_dict = {
        "start_time": start_time,
        "end_time": end_time,
        "error_count": error_count,
        "response_times": response_times,
        "average_latency_by_time": average_latencies,
        "average_latency_by_clients": average_latency_by_clients,
        "successes_by_time": success_buckets,
        "errors_by_time": error_buckets,
        "requests_by_time": total_request_buckets,
        "clients_by_time": client_buckets,
    }
    return LoadTestResults(**output_dict)


class ThroughputResults(BaseModel):
    requests_per_second: float
    successes_per_second: float
    errors_per_second: float


def plot_throughput_by_time(
    successes: dict[datetime, int],
    errors: dict[datetime, int],
    requests: dict[datetime, int],
    clients: dict[datetime, int],
    start_time: datetime,
    output_dir: str = "./plots",
):
    """Plot number of clients vs throughput, success rate, and error rate, then save to a file."""
    # Ensure the output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # Filepath for saving the figure
    output_file = os.path.join(output_dir, "time_vs_throughput.png")

    # Sort the latency data by time
    success_times, success_rate = zip(*sorted(successes.items()))
    error_times, error_rate = zip(*sorted(errors.items()))
    request_times, request_rate = zip(*sorted(requests.items()))
    client_times, num_clients = zip(*sorted(clients.items()))
    expected_response_rate = [REQUESTS_PER_SECOND * client_count for client_count in num_clients]

    # Calculate elapsed time in seconds
    success_elapsed_seconds = [(time - start_time).total_seconds() for time in success_times]
    error_elapsed_seconds = [(time - start_time).total_seconds() for time in error_times]
    request_elapsed_seconds = [(time - start_time).total_seconds() for time in request_times]
    client_elapsed_seconds = [(time - start_time).total_seconds() for time in client_times]

    # Create the main plot
    fig, ax1 = plt.subplots(figsize=(8, 6))

    # Plot throughput, successes, and errors on the main y-axis
    ax1.plot(request_elapsed_seconds, request_rate, linestyle="-", label="Throughput (Requests/s)", alpha=0.8)
    ax1.plot(success_elapsed_seconds, success_rate, linestyle="--", label="Successes (Requests/s)", alpha=0.8)
    ax1.plot(error_elapsed_seconds, error_rate, linestyle="-", label="Errors (Requests/s)", alpha=0.8)
    ax1.plot(client_elapsed_seconds, expected_response_rate, linestyle="-", label="Expected Requests/s", alpha=0.8)

    ax1.set_xlabel("Elapsed Time (s)")
    ax1.set_ylabel("Requests / Second")
    ax1.grid(True)
    ax1.legend(loc="upper left")

    # Set a fixed y-axis limit to avoid it adjusting based on the expected response rate
    ax1.set_ylim((0, max(*request_rate, *success_rate, *error_rate) * 1.4))

    # Create a secondary y-axis for the number of clients
    ax2 = ax1.twinx()
    ax2.plot(client_elapsed_seconds, num_clients, linestyle="-", color="purple", label="Num Clients", alpha=1)
    ax2.set_ylabel("Number of Clients")
    ax2.legend(loc="upper right")

    # Set title and save the figure
    plt.title("Elapsed Time vs Throughput, Successes, Errors, and Clients")
    plt.savefig(output_file)

    # Print the file path to the saved plot
    print(f"Plot saved to: {output_file}")


def plot_throughput_by_clients(client_throughput: dict[int, ThroughputResults], output_dir: str = "./plots"):
    """Plot number of clients vs throughput, success rate, and error rate, then save to a file."""
    num_clients = []
    throughputs = []
    successes = []
    errors = []

    for num_workers, results in client_throughput.items():
        num_clients.append(num_workers)
        throughputs.append(results.requests_per_second)
        successes.append(results.successes_per_second)
        errors.append(results.errors_per_second)

    # Ensure the output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # Filepath for saving the figure
    output_file = os.path.join(output_dir, "clients_vs_throughput.png")

    # Plot
    plt.figure(figsize=(8, 6))
    plt.plot(num_clients, throughputs, marker="o", linestyle="-", label="Throughput (Requests/s)", alpha=0.8)
    plt.plot(num_clients, successes, marker="s", linestyle="--", label="Successes (Requests/s)", alpha=0.8)
    plt.plot(num_clients, errors, marker="^", linestyle=":", label="Errors (Requests/s)", alpha=0.8)

    plt.title("Number of Clients vs Throughput, Successes, and Errors")
    plt.xlabel("Number of Clients (Processes)")
    plt.ylabel("Rate (Requests per Second)")
    plt.grid(True)
    plt.legend()

    # Save the figure to the output file
    plt.savefig(output_file)

    # Print the file path to the saved plot
    print(f"Plot saved to: {output_file}")


def plot_latency_over_time(
    average_latencies: dict[datetime, float],
    start_time: datetime,
    output_dir: str = "./plots",
):
    """Plot average latency over elapsed time (in seconds) with vertical lines for client increases."""
    if average_latencies:
        # Sort the latency data by time
        times, avg_latencies = zip(*sorted(average_latencies.items()))

        # Calculate elapsed time in seconds
        elapsed_seconds = [(time - start_time).total_seconds() for time in times]

        # Ensure the output directory exists
        os.makedirs(output_dir, exist_ok=True)

        # Filepath for saving the figure
        output_file = os.path.join(output_dir, "average_latency_over_time.png")

        # Plot
        plt.figure(figsize=(8, 6))
        plt.plot(elapsed_seconds, avg_latencies, marker="o", linestyle="-", label="Average Latency (ms)")
        plt.title("Average Latency Over Elapsed Time")
        plt.xlabel("Elapsed Time (seconds)")
        plt.ylabel("Latency (s)")
        plt.grid(True)

        # Save the figure to the output file
        plt.savefig(output_file)

        # Print the file path to the saved plot
        print(f"Plot saved to: {output_file}")
    else:
        print("No data to plot.")


def plot_latency_vs_clients(average_latencies: dict[int, float], output_dir: str = "./plots"):
    """Plot average latency vs number of clients and save to a file."""
    if average_latencies:
        # Sort the latency data by number of clients
        clients, avg_latencies = zip(*sorted(average_latencies.items()))

        # Ensure the output directory exists
        os.makedirs(output_dir, exist_ok=True)

        # Filepath for saving the figure
        output_file = os.path.join(output_dir, "latency_vs_clients.png")

        # Plot
        plt.figure(figsize=(8, 6))
        plt.plot(clients, avg_latencies, marker="o", linestyle="-", label="Average Latency (ms)")
        plt.title("Average Latency vs Number of Clients")
        plt.xlabel("Number of Clients")
        plt.ylabel("Latency (s)")
        plt.grid(True)

        # Save the figure to the output file
        plt.savefig(output_file)

        # Print the file path to the saved plot
        print(f"Plot saved to: {output_file}")
    else:
        print("No data to plot.")


def show_load_test_results():
    log_file = "./logs/load_test_log.txt"  # Path to the log file

    if not os.path.exists(log_file):
        print(f"Log file {log_file} not found.")
    else:
        load_test_results = parse_log_file(log_file)

        plot_throughput_by_time(
            load_test_results.successes_by_time,
            load_test_results.errors_by_time,
            load_test_results.requests_by_time,
            load_test_results.clients_by_time,
            load_test_results.start_time,
        )
        plot_latency_over_time(load_test_results.average_latency_by_time, load_test_results.start_time)
        plot_latency_vs_clients(load_test_results.average_latency_by_clients)


if __name__ == "__main__":
    show_load_test_results()


# def print_static_results(workers, first_time, last_time, error_count, response_times):
#     """Prints the standard results for static mode."""
#     total_seconds = last_time - first_time
#     total_requests = len(response_times)
#     requests_per_second = total_requests / total_seconds if total_seconds > 0 else 0
#     errors_per_second = error_count / total_seconds if total_seconds > 0 else 0
#     average_response_time = sum(response_times) / len(response_times) if response_times else 0.0
#     median_response_time = statistics.median(response_times) if response_times else 0.0
#     max_response_time = max(response_times) if response_times else 0.0

#     aggregate_error_percentage = error_count / total_requests if total_requests > 0 else 0
#     requests_per_second_per_worker = requests_per_second / len(workers)

#     print("Aggregate Results:")
#     print(f"  # of Processes: {len(workers)}")
#     print(f"  Total Seconds: {total_seconds}")
#     print(f"  Total Requests: {total_requests}")
#     print(f"  Average Requests per Second: {requests_per_second:.2f}")
#     print(f"  Average Requests per Second per Process: {requests_per_second_per_worker:.2f}")
#     print(f"  Total Errors: {error_count}")
#     print(f"  Total Error Percentage: {aggregate_error_percentage * 100:.2f}%")
#     print(f"  Average Errors per Second: {errors_per_second:.4f}")
#     print(f"  Average Response Time: {average_response_time:.4f} seconds")
#     print(f"  Median Response Time: {median_response_time:.4f} seconds")
#     print(f"  Maximum Response Time: {max_response_time:.4f} seconds")
