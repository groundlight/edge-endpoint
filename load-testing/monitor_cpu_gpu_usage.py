import argparse
import os
import time

import GPUtil
import matplotlib.pyplot as plt
import psutil
from pydantic import BaseModel

OUTPUT_DIR = "./plots"


class MonitoringResults(BaseModel):
    elapsed_time: list[float]
    cpu_usage: list[float]
    memory_usage: list[float]
    gpu_data: dict[int, dict[str, list[float]]]


def monitor_system(duration: int):
    """Monitors CPU and GPU usage for the specified duration."""
    elapsed_time = []
    cpu_usage = []
    memory_usage = []
    gpu_data = {}

    print(f"Monitoring system for {duration} seconds...")

    # Get GPU devices
    gpus = GPUtil.getGPUs()
    for gpu in gpus:
        gpu_data[gpu.id] = {"elapsed_time": [], "gpu_usage": [], "memory_usage": []}

    start_time = time.time()

    while (time.time() - start_time) < duration:
        elapsed = time.time() - start_time

        # Collect CPU and memory data
        cpu = psutil.cpu_percent(interval=1.0)
        memory = psutil.virtual_memory().percent

        # Append to lists
        elapsed_time.append(elapsed)
        cpu_usage.append(cpu)
        memory_usage.append(memory)

        # Collect GPU data
        gpus = GPUtil.getGPUs()
        for gpu in gpus:
            gpu_data[gpu.id]["elapsed_time"].append(elapsed)
            gpu_data[gpu.id]["gpu_usage"].append(gpu.load * 100)  # Convert to percentage
            gpu_data[gpu.id]["memory_usage"].append(gpu.memoryUtil * 100)  # Convert to percentage

        print(f"Elapsed Time: {elapsed:.2f}s, CPU: {cpu}%, Memory: {memory}%")
        for gpu in gpus:
            print(f"GPU {gpu.id}: Usage: {gpu.load*100:.2f}%, Memory: {gpu.memoryUtil*100:.2f}%")

    results = {
        "elapsed_time": elapsed_time,
        "cpu_usage": cpu_usage,
        "memory_usage": memory_usage,
        "gpu_data": gpu_data,
    }
    return MonitoringResults(**results)


def plot_cpu_data(elapsed_time: list[float], cpu_usage: list[float], memory_usage: list[float]):
    """Plots CPU usage and memory."""
    # Create figure for CPU and Memory
    plt.figure(figsize=(12, 6))

    # Plot CPU usage
    plt.subplot(2, 1, 1)
    plt.plot(elapsed_time, cpu_usage, label="CPU Usage (%)", color="blue")
    plt.xlabel("Elapsed Time (s)")
    plt.ylabel("CPU Usage (%)")
    plt.title("CPU Usage Over Time")
    plt.grid(True)

    # Plot Memory usage
    plt.subplot(2, 1, 2)
    plt.plot(elapsed_time, memory_usage, label="Memory Usage (%)", color="red")
    plt.xlabel("Elapsed Time (s)")
    plt.ylabel("Memory Usage (%)")
    plt.title("Memory Usage Over Time")
    plt.grid(True)

    plt.tight_layout()
    output_file = os.path.join(OUTPUT_DIR, "cpu_monitoring.png")
    plt.savefig(output_file)
    plt.show()
    print(f"CPU and Memory graphs saved to {output_file}")


def plot_gpu_data(gpu_data: dict[int, dict[str, list[float]]]):
    "Plots GPU usage and memory."
    # Create separate plots for each GPU
    for gpu_id, data in gpu_data.items():
        plt.figure(figsize=(12, 6))

        # Plot GPU usage
        plt.subplot(2, 1, 1)
        plt.plot(data["elapsed_time"], data["gpu_usage"], label=f"GPU {gpu_id} Usage (%)", color="green")
        plt.xlabel("Elapsed Time (s)")
        plt.ylabel("GPU Usage (%)")
        plt.title(f"GPU {gpu_id} Usage Over Time")
        plt.grid(True)

        # Plot GPU Memory usage
        plt.subplot(2, 1, 2)
        plt.plot(data["elapsed_time"], data["memory_usage"], label=f"GPU {gpu_id} Memory Usage (%)", color="purple")
        plt.xlabel("Elapsed Time (s)")
        plt.ylabel("GPU Memory Usage (%)")
        plt.title(f"GPU {gpu_id} Memory Usage Over Time")
        plt.grid(True)

        # Save and show
        output_file = os.path.join(OUTPUT_DIR, f"gpu_{gpu_id}_monitoring.png")
        plt.tight_layout()
        plt.savefig(output_file)
        plt.show()
        print(f"GPU {gpu_id} graphs saved to {output_file}")


if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    parser = argparse.ArgumentParser(description="System Monitoring Script")
    parser.add_argument("duration", type=int, help="Total time to monitor (in seconds)")
    args = parser.parse_args()

    results = monitor_system(args.duration)
    plot_cpu_data(results.elapsed_time, results.cpu_usage, results.memory_usage)
    plot_gpu_data(results.gpu_data)
