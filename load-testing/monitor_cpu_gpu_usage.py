import sys
import time

import GPUtil
import psutil


def log_usage(duration):
    with open("usage_log.txt", "w") as log_file:
        start_time = time.time()
        while time.time() - start_time < duration:
            # Get the current timestamp
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

            # Log the timestamp
            log_file.write(f"Timestamp: {timestamp}\n")

            # Log CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            log_file.write(f"CPU Usage: {cpu_percent}%\n")
            log_file.write(f"Memory Usage: {memory.percent}%\n")

            # Log GPU usage
            gpus = GPUtil.getGPUs()
            for gpu in gpus:
                gpu_memory_percent = (gpu.memoryUsed / gpu.memoryTotal) * 100  # Calculate memory usage as percent
                log_file.write(f"GPU {gpu.id} Usage: {gpu.load*100}%\n")
                log_file.write(f"GPU {gpu.id} Memory Usage: {gpu_memory_percent:.2f}%\n")

            log_file.write("-" * 20 + "\n")
            log_file.flush()
            time.sleep(1)  # Log every 1 second


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python script_name.py <duration_in_seconds>")
        sys.exit(1)

    duration = int(sys.argv[1])
    log_usage(duration)
