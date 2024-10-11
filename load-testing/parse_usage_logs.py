import re
from datetime import datetime


def parse_logs(file_path):
    cpu_usage = []
    memory_usage = []
    gpu_usage = {}
    gpu_memory_usage = {}
    timestamps = []

    with open(file_path, "r") as log_file:
        for line in log_file:
            # Check for timestamp
            if "Timestamp" in line:
                timestamp_str = re.search(r"Timestamp: (.+)", line).group(1)
                timestamps.append(datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S"))

            # Check for CPU usage
            elif "CPU Usage" in line:
                cpu_percent = float(re.search(r"(\d+\.?\d*)%", line).group(1))
                cpu_usage.append(cpu_percent)

            # Check for memory usage
            elif "Memory Usage" in line and "GPU" not in line:
                memory_percent = float(re.search(r"(\d+\.?\d*)%", line).group(1))
                memory_usage.append(memory_percent)

            # Check for GPU usage
            elif "GPU" in line and "Usage" in line and "Memory" not in line:
                gpu_id = int(re.search(r"GPU (\d+)", line).group(1))
                gpu_percent = float(re.search(r"(\d+\.?\d*)%", line).group(1))
                if gpu_id not in gpu_usage:
                    gpu_usage[gpu_id] = []
                gpu_usage[gpu_id].append(gpu_percent)

            # Check for GPU memory usage
            elif "GPU" in line and "Memory Usage" in line:
                gpu_id = int(re.search(r"GPU (\d+)", line).group(1))
                gpu_memory_percent = float(re.search(r"(\d+\.?\d*)%", line).group(1))
                if gpu_id not in gpu_memory_usage:
                    gpu_memory_usage[gpu_id] = []
                gpu_memory_usage[gpu_id].append(gpu_memory_percent)

    return cpu_usage, memory_usage, gpu_usage, gpu_memory_usage, timestamps


def calculate_averages(usage_list):
    if len(usage_list) == 0:
        return 0
    return sum(usage_list) / len(usage_list)


def calculate_time_span(timestamps):
    if len(timestamps) < 2:
        return None
    start_time = timestamps[0]
    end_time = timestamps[-1]
    return end_time - start_time


def main():
    file_path = "usage_log.txt"

    cpu_usage, memory_usage, gpu_usage, gpu_memory_usage, timestamps = parse_logs(file_path)

    if timestamps:
        time_span = calculate_time_span(timestamps)
        if time_span:
            print(f"Time span of logs: {time_span}")
        else:
            print("Not enough timestamps to calculate time span.")
    else:
        print("No timestamps found in the log file.")

    print(f"Average CPU Usage: {calculate_averages(cpu_usage):.2f}%")
    print(f"Average Memory Usage: {calculate_averages(memory_usage):.2f}%")

    for gpu_id in gpu_usage:
        print(f"Average GPU {gpu_id} Usage: {calculate_averages(gpu_usage[gpu_id]):.2f}%")

    for gpu_id in gpu_memory_usage:
        print(f"Average GPU {gpu_id} Memory Usage: {calculate_averages(gpu_memory_usage[gpu_id]):.2f}%")


if __name__ == "__main__":
    main()
