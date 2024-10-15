import datetime as dt
import json
import os
import re
from datetime import datetime
from typing import Any

import matplotlib.pyplot as plt
from pydantic import BaseModel


class LoadTestResults(BaseModel):
    throughput_data: dict[int, dict[str, Any]]
    start_time: datetime
    end_time: datetime
    error_count: int
    response_times: list[float]
    average_latency_by_time: dict[datetime, float]
    average_latency_by_clients: dict[int, float]


def parse_log_file(log_file: str) -> LoadTestResults:
    """Parse the log file to gather throughput data for static or ramp-up mode."""
    response_times = []  # To track response times for each request
    error_count = 0
    start_time, end_time = None, None

    throughput_data = {}  # Dictionary to store throughput per number of workers
    latency_buckets = {}
    latency_by_clients = {}  # Track latencies by the number of clients

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

                # Track latencies by the number of clients
                if num_clients not in latency_by_clients:
                    latency_by_clients[num_clients] = []

                latency_by_clients[num_clients].append(log_data["latency"])

                # Count requests and throughput based on the number of workers
                if num_clients not in throughput_data:
                    throughput_data[num_clients] = {
                        "start_time": timestamp,
                        "requests": 0,
                        "errors": 0,
                        "latencies": [],
                    }

                throughput_data[num_clients]["requests"] += 1
                throughput_data[num_clients]["latencies"].append(log_data["latency"])
                if not log_data["success"]:
                    throughput_data[num_clients]["errors"] += 1
                throughput_data[num_clients]["end_time"] = timestamp

    # Calculate average latencies for each time bucket
    average_latencies = {bucket: sum(latencies) / len(latencies) for bucket, latencies in latency_buckets.items()}

    # Calculate average latencies for each client count
    average_latency_by_clients = {
        clients: sum(latencies) / len(latencies) for clients, latencies in latency_by_clients.items()
    }

    output_dict = {
        "throughput_data": throughput_data,
        "start_time": start_time,
        "end_time": end_time,
        "error_count": error_count,
        "response_times": response_times,
        "average_latency_by_time": average_latencies,
        "average_latency_by_clients": average_latency_by_clients,
    }
    return LoadTestResults(**output_dict)


class ThroughputResults(BaseModel):
    requests_per_second: float
    successes_per_second: float
    errors_per_second: float


def calculate_throughput(throughput_data: dict[int, dict[str, Any]]) -> dict[int, ThroughputResults]:
    """Calculate throughput (requests per second) for each client count."""
    client_throughput: dict[int, ThroughputResults] = {}

    def calculate_rate(num_items: int, time_span: float) -> float:
        return num_items / time_span if time_span > 0 else 0.0

    for num_workers, data in throughput_data.items():
        total_requests: int = data["requests"]
        num_errors: int = data["errors"]
        num_successes: int = total_requests - num_errors

        total_seconds: float = (data["end_time"] - data["start_time"]).total_seconds()
        requests_per_second = calculate_rate(total_requests, total_seconds)
        successes_per_second = calculate_rate(num_successes, total_seconds)
        errors_per_second = calculate_rate(num_errors, total_seconds)

        throughput_results = ThroughputResults(
            requests_per_second=requests_per_second,
            successes_per_second=successes_per_second,
            errors_per_second=errors_per_second,
        )

        client_throughput[num_workers] = throughput_results

    return client_throughput


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


def plot_throughput(client_throughput: dict[int, ThroughputResults], output_dir: str = "./plots"):
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
    throughput_data: dict[int, dict[str, Any]],
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
        output_file = os.path.join(output_dir, "average_latency_with_clients.png")

        # Plot
        plt.figure(figsize=(8, 6))
        plt.plot(elapsed_seconds, avg_latencies, marker="o", linestyle="-", label="Average Latency (ms)")
        plt.title("Average Latency Over Elapsed Time with Client Increases")
        plt.xlabel("Elapsed Time (seconds)")
        plt.ylabel("Latency (ms)")
        plt.grid(True)

        # Add vertical lines for when the number of clients increased
        for num_clients, data in throughput_data.items():
            # Calculate elapsed time when the number of clients increased
            client_increase_time = (data["start_time"] - start_time).total_seconds()

            # Add vertical line at the time the number of clients increased
            plt.axvline(x=client_increase_time, color="r", linestyle="--", alpha=0.7)

            # Annotate the number of clients at the top of the plot
            plt.text(
                client_increase_time,
                max(avg_latencies),
                f"{num_clients} clients",
                rotation=90,
                verticalalignment="bottom",
                color="r",
            )

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
        plt.ylabel("Latency (ms)")
        plt.grid(True)

        # Save the figure to the output file
        plt.savefig(output_file)

        # Print the file path to the saved plot
        print(f"Plot saved to: {output_file}")
    else:
        print("No data to plot.")


def show_load_test_results():
    log_file = "./logs/load_test_log.txt"  # Path to the single log file

    if not os.path.exists(log_file):
        print(f"Log file {log_file} not found.")
    else:
        load_test_results = parse_log_file(log_file)

        # # Determine if this is a ramp-up run or a static run
        # if len(throughput_data) == 1:  # Static mode: Only one client count
        #     print_static_results(workers, first_time, last_time, error_count, response_times)
        # else:  # Ramp-up mode: Multiple client counts
        client_throughput = calculate_throughput(load_test_results.throughput_data)
        plot_throughput(client_throughput)
        plot_latency_over_time(
            load_test_results.average_latency_by_time, load_test_results.start_time, load_test_results.throughput_data
        )
        plot_latency_vs_clients(load_test_results.average_latency_by_clients)


if __name__ == "__main__":
    show_load_test_results()
