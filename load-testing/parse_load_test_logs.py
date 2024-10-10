import os
import statistics


def calculate_requests_errors_response_times(log_file):
    """Calculate requests per second, count errors, errors per second, and calculate average/median/max response time from the log file."""
    request_times = []
    response_times = []  # To track response times for each request
    error_count = 0
    first_time, last_time = None, None

    # Read the log file and extract request start timestamps, response times, and errors
    with open(log_file) as file:
        for line in file:
            if "Request Start" in line:
                # Extract the Unix timestamp from the log line
                timestamp_str = line.split("|")[1].strip().split(": ")[1]
                timestamp = float(timestamp_str)
                request_times.append(timestamp)
                if first_time is None:
                    first_time = timestamp  # Record first request time
                last_time = timestamp  # Continuously update last request time

            if "Response Time" in line:
                # Extract the response time from the log
                response_time_str = line.split("|")[2].strip().split(": ")[1].split()[0]
                response_time = float(response_time_str)
                response_times.append(response_time)

            if "Error" in line:
                error_count += 1

    if not request_times:
        return 0, 0, 0, 0, 0, 0, 0  # No requests found

    # Calculate total duration
    total_seconds = last_time - first_time if first_time and last_time else 0

    # Calculate requests per second
    total_requests = len(request_times)
    requests_per_second = total_requests / total_seconds if total_seconds > 0 else 0

    # Calculate errors per second
    errors_per_second = error_count / total_seconds if total_seconds > 0 else 0

    # Calculate average response time
    average_response_time = sum(response_times) / len(response_times) if response_times else 0

    # Calculate median response time
    median_response_time = statistics.median(response_times) if response_times else 0

    # Calculate maximum response time
    max_response_time = max(response_times) if response_times else 0

    return (
        total_requests,
        requests_per_second,
        error_count,
        errors_per_second,
        average_response_time,
        median_response_time,
        max_response_time,
    )


def process_all_logs(log_dir):
    """Process all log files in the directory and calculate stats, including errors, response times, and maximum response time."""
    total_requests_aggregate = 0
    total_time_aggregate = 0
    total_error_count = 0
    total_errors_per_second_aggregate = 0
    total_response_time_aggregate = 0
    total_median_response_time_aggregate = []
    max_response_time_aggregate = 0
    process_count = 0

    for log_file in os.listdir(log_dir):
        if log_file.startswith("process_") and log_file.endswith(".log"):
            log_file_path = os.path.join(log_dir, log_file)
            (
                total_requests,
                requests_per_second,
                error_count,
                errors_per_second,
                average_response_time,
                median_response_time,
                max_response_time,
            ) = calculate_requests_errors_response_times(log_file_path)

            if total_requests > 0:
                process_count += 1
                # print(f"Results for {log_file}:")
                # print(f"  Total Requests: {total_requests}")
                # print(f"  Requests per Second: {requests_per_second:.2f}")
                # print(f"  Errors: {error_count}")
                # print(f"  Errors per Second: {errors_per_second:.4f}")
                # print(f"  Average Response Time: {average_response_time:.4f} seconds")
                # print(f"  Median Response Time: {median_response_time:.4f} seconds")
                # print(f"  Maximum Response Time: {max_response_time:.4f} seconds\n")

                total_requests_aggregate += total_requests
                total_time_aggregate += total_requests / requests_per_second
                total_error_count += error_count
                total_errors_per_second_aggregate += errors_per_second
                total_response_time_aggregate += average_response_time
                total_median_response_time_aggregate.append(median_response_time)

                # Track the maximum response time across all processes
                max_response_time_aggregate = max(max_response_time, max_response_time_aggregate)

    if total_requests_aggregate > 0 and total_time_aggregate > 0:
        average_rps = total_requests_aggregate / total_time_aggregate
        average_errors = total_error_count / process_count if process_count > 0 else 0
        average_errors_per_second = total_errors_per_second_aggregate / process_count if process_count > 0 else 0
        average_errors_per_process_per_second = average_errors_per_second / process_count if process_count > 0 else 0
        average_response_time_aggregate = total_response_time_aggregate / process_count if process_count > 0 else 0
        median_response_time_aggregate = (
            statistics.median(total_median_response_time_aggregate) if total_median_response_time_aggregate else 0
        )

        aggregate_error_percentage = total_error_count / total_requests_aggregate

        print("Aggregate Results:")
        print(f"  Total Requests (All Processes): {total_requests_aggregate}")
        print(f"  Average Requests per Second: {average_rps:.2f}")
        print(f"  Total Errors (All Processes): {total_error_count}")
        print(f"  Total Error Percentage (All Processes): {aggregate_error_percentage*100:.2f}%")
        print(f"  Average Errors per Process: {average_errors:.2f}")
        print(f"  Average Errors per Second: {average_errors_per_second:.4f}")
        print(f"  Average Errors per Process per Second: {average_errors_per_process_per_second:.4f}")
        print(f"  Average Response Time (All Processes): {average_response_time_aggregate:.4f} seconds")
        print(f"  Median Response Time (All Processes): {median_response_time_aggregate:.4f} seconds")
        print(f"  Maximum Response Time (All Processes): {max_response_time_aggregate:.4f} seconds")
    else:
        print("No valid log files found.")


if __name__ == "__main__":
    log_dir = "./logs"  # Path to the logs directory

    if not os.path.exists(log_dir):
        print(f"Log directory {log_dir} not found.")
    else:
        process_all_logs(log_dir)
