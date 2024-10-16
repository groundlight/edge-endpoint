import os
import time

import GPUtil
import matplotlib.pyplot as plt
import psutil

# Parameters
duration = 358  # Total time to monitor (in seconds)
interval = 1  # Time between each measurement (in seconds)
output_dir = "./plots"

# Ensure the output directory exists
os.makedirs(output_dir, exist_ok=True)

# Lists to store CPU and Memory data
elapsed_time = []
cpu_usage = []
memory_usage = []

# Dictionary to store GPU data per device
gpu_data = {}


def monitor_system(duration, interval):
    print(f"Monitoring system for {duration} seconds...")
    start_time = time.time()

    # Get GPU devices
    gpus = GPUtil.getGPUs()
    for gpu in gpus:
        gpu_data[gpu.id] = {"elapsed_time": [], "gpu_usage": [], "memory_usage": []}

    while (time.time() - start_time) < duration:
        # Collect CPU and memory data
        cpu = psutil.cpu_percent(interval=interval)
        memory = psutil.virtual_memory().percent
        elapsed = time.time() - start_time

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


def plot_cpu_memory(elapsed_time, cpu_usage, memory_usage):
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
    output_file = os.path.join(output_dir, "cpu_memory_monitoring.png")
    plt.savefig(output_file)
    plt.show()
    print(f"CPU and Memory graphs saved to {output_file}")


def plot_gpu_data(gpu_data):
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
        output_file = os.path.join(output_dir, f"gpu_{gpu_id}_monitoring.png")
        plt.tight_layout()
        plt.savefig(output_file)
        plt.show()
        print(f"GPU {gpu_id} graphs saved to {output_file}")


if __name__ == "__main__":
    monitor_system(duration, interval)
    plot_cpu_memory(elapsed_time, cpu_usage, memory_usage)
    plot_gpu_data(gpu_data)
