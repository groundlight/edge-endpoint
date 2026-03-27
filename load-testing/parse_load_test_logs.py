from argparse import Namespace
import json
import os
import re
from datetime import datetime
from math import ceil, floor
from typing import Any

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
    ram_by_time: dict[datetime, float]
    vram_by_time: dict[datetime, float]


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


class ThroughputSummary(BaseModel):
    maximum_rps: float = 0.0
    maximum_steady_rps: float | None = None
    maximum_steady_clients: int | None = None
    maximum_steady_ramp: int | None = None

class SystemUtilizationSummary(BaseModel):
    average_gpu_utilization_during_max_steady_ramp: float
    average_cpu_utilization_during_max_steady_ramp: float
    average_ram_utilization_during_max_steady_ramp: float
    average_vram_utilization_during_max_steady_ramp: float

STEADY_THROUGHPUT_RATIO = 0.95
STEADY_SUCCESS_RATE = 0.99


def _event_timestamp_seconds(log_data: dict[str, Any]) -> float:
    """Return event timestamp in epoch seconds."""
    timestamp = log_data.get("ts")
    if timestamp is not None:
        return float(timestamp)
    return datetime.strptime(log_data["asctime"], "%Y-%m-%d %H:%M:%S").timestamp()


def _to_datetime_series(start_ts: float, buckets: dict[int, Any]) -> dict[datetime, Any]:
    """Convert second-offset buckets to datetime-keyed series."""
    return {datetime.fromtimestamp(start_ts + bucket_idx): value for bucket_idx, value in sorted(buckets.items())}


def _parse_bucketed_series(log_file: str) -> dict[str, Any]:
    """Parse log file into fixed 1-second bucketed series and ramp transitions."""
    entries: list[dict[str, Any]] = []
    with open(log_file) as file:
        for line in file:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("RAMP"):
                client_match = re.search(r"\d+", stripped)
                if not client_match:
                    continue
                ramp_ts_match = re.search(r"ts=(\d+(?:\.\d+)?)", stripped)
                entries.append(
                    {
                        "type": "ramp",
                        "clients": int(client_match.group()),
                        "ts": float(ramp_ts_match.group(1)) if ramp_ts_match else None,
                    }
                )
                continue
            if not stripped.startswith("{"):
                continue
            payload = json.loads(stripped)
            entries.append(
                {
                    "type": payload.get("event", "request"),
                    "ts": _event_timestamp_seconds(payload),
                    "payload": payload,
                }
            )

    request_times = [entry["ts"] for entry in entries if entry["type"] == "request"]
    if not request_times:
        raise RuntimeError("Log file did not contain request events.")
    first_ramp_times = [entry["ts"] for entry in entries if entry["type"] == "ramp" and entry["ts"] is not None]
    start_ts = first_ramp_times[0] if first_ramp_times else request_times[0]
    latest_request_ts = max(request_times)
    full_seconds = max(1, int(latest_request_ts - start_ts))

    requests_by_second: dict[int, int] = {}
    errors_by_second: dict[int, int] = {}
    latencies_by_second: dict[int, list[float]] = {}
    cpu_by_second: dict[int, list[float]] = {}
    ram_by_second: dict[int, list[float]] = {}
    gpu_by_second: dict[int, list[float]] = {}
    vram_by_second: dict[int, list[float]] = {}
    ramp_transitions: list[tuple[int, int]] = []
    current_clients = 0

    for entry in entries:
        if entry["type"] == "ramp":
            current_clients = int(entry["clients"])
            ramp_ts = entry["ts"] if entry["ts"] is not None else start_ts
            ramp_second = max(0, int(ramp_ts - start_ts))
            ramp_transitions.append((ramp_second, current_clients))
            continue

        event_ts = float(entry["ts"])
        bucket_idx = int(event_ts - start_ts)
        if bucket_idx < 0:
            continue
        payload = entry["payload"]
        event_type = entry["type"]

        if event_type == "request":
            if bucket_idx >= full_seconds:
                continue
            requests_by_second[bucket_idx] = requests_by_second.get(bucket_idx, 0) + 1
            errors_by_second.setdefault(bucket_idx, 0)
            latencies_by_second.setdefault(bucket_idx, []).append(float(payload.get("latency", 0.0)))
            if not payload.get("success", False):
                errors_by_second[bucket_idx] += 1
        elif event_type == "cpu":
            cpu_by_second.setdefault(bucket_idx, []).append(float(payload.get("cpu_percent", 0.0)))
            memory_percent = payload.get("memory_percent")
            if memory_percent is not None:
                ram_by_second.setdefault(bucket_idx, []).append(float(memory_percent))
        elif event_type == "gpu":
            gpu_by_second.setdefault(bucket_idx, []).append(float(payload.get("gpu_utilization", 0.0)))
            vram_by_second.setdefault(bucket_idx, []).append(float(payload.get("vram_utilization", 0.0)))

    clients_by_second: dict[int, int] = {}
    if ramp_transitions:
        ramp_transitions.sort(key=lambda item: item[0])
        active_clients = ramp_transitions[0][1]
        transition_idx = 0
        for second_idx in range(full_seconds):
            while transition_idx + 1 < len(ramp_transitions) and ramp_transitions[transition_idx + 1][0] <= second_idx:
                transition_idx += 1
                active_clients = ramp_transitions[transition_idx][1]
            clients_by_second[second_idx] = active_clients
    else:
        for second_idx in range(full_seconds):
            clients_by_second[second_idx] = current_clients

    for second_idx in range(full_seconds):
        requests_by_second.setdefault(second_idx, 0)
        errors_by_second.setdefault(second_idx, 0)
        latencies_by_second.setdefault(second_idx, [])

    return {
        "start_ts": start_ts,
        "full_seconds": full_seconds,
        "requests_by_second": requests_by_second,
        "errors_by_second": errors_by_second,
        "clients_by_second": clients_by_second,
        "latencies_by_second": latencies_by_second,
        "gpu_by_second": gpu_by_second,
        "cpu_by_second": cpu_by_second,
        "ram_by_second": ram_by_second,
        "vram_by_second": vram_by_second,
    }


def parse_log_file(log_file: str) -> LoadTestResults:
    """Parse the log file into fixed 1-second bucketed time series."""
    parsed = _parse_bucketed_series(log_file)
    start_ts = parsed["start_ts"]
    average_latencies = _to_datetime_series(
        start_ts,
        {
            second: (sum(values) / len(values))
            for second, values in parsed["latencies_by_second"].items()
            if values
        },
    )
    average_gpu = _to_datetime_series(
        start_ts,
        {
            second: (sum(values) / len(values))
            for second, values in parsed["gpu_by_second"].items()
            if values
        },
    )
    average_cpu = _to_datetime_series(
        start_ts,
        {
            second: (sum(values) / len(values))
            for second, values in parsed["cpu_by_second"].items()
            if values
        },
    )
    average_ram = _to_datetime_series(
        start_ts,
        {
            second: (sum(values) / len(values))
            for second, values in parsed["ram_by_second"].items()
            if values
        },
    )
    average_vram = _to_datetime_series(
        start_ts,
        {
            second: (sum(values) / len(values))
            for second, values in parsed["vram_by_second"].items()
            if values
        },
    )

    return LoadTestResults(
        start_time=datetime.fromtimestamp(start_ts),
        average_latency_by_time=average_latencies,
        errors_by_time=_to_datetime_series(start_ts, parsed["errors_by_second"]),
        requests_by_time=_to_datetime_series(start_ts, parsed["requests_by_second"]),
        clients_by_time=_to_datetime_series(start_ts, parsed["clients_by_second"]),
        gpu_by_time=average_gpu,
        cpu_by_time=average_cpu,
        ram_by_time=average_ram,
        vram_by_time=average_vram,
    )


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


def summarize_throughput(
    log_file: str,
    requests_per_second: int,
    bucket_duration_hint_sec: int | None = None,
) -> ThroughputSummary:
    """Compute throughput summary for the log file."""


    bucket_metrics = _calculate_bucket_metrics(log_file, requests_per_second)
    if not bucket_metrics:
        return ThroughputSummary()

    max_rps_bucket = max(bucket_metrics, key=lambda bucket: bucket.achieved_rps)
    steady_buckets = [bucket for bucket in bucket_metrics if bucket.is_steady]
    if steady_buckets:
        max_steady_bucket = max(steady_buckets, key=lambda bucket: bucket.achieved_rps)
        return ThroughputSummary(
            maximum_rps=max_rps_bucket.achieved_rps,
            maximum_steady_rps=max_steady_bucket.expected_rps,
            maximum_steady_clients=max_steady_bucket.num_clients,
            maximum_steady_ramp=max_steady_bucket.num_clients,
        )

    return ThroughputSummary(maximum_rps=max_rps_bucket.achieved_rps)


def summarize_system_utilization(
    log_file: str,
    maximum_steady_ramp: int | None,
) -> SystemUtilizationSummary | None:
    """Estimate system utilization while running the maximum steady ramp."""
    if maximum_steady_ramp is None or maximum_steady_ramp <= 0:
        return None

    load_test_results = parse_log_file(log_file)
    if not load_test_results.requests_by_time:
        raise RuntimeError("Log file did not contain request time series.")

    candidate_times = [
        timestamp
        for timestamp, clients in load_test_results.clients_by_time.items()
        if clients == maximum_steady_ramp
    ]
    if not candidate_times:
        raise RuntimeError("No time buckets matched the maximum steady ramp.")

    window_start = min(candidate_times)
    window_end = max(candidate_times)

    gpu_samples = [
        value
        for timestamp, value in load_test_results.gpu_by_time.items()
        if window_start <= timestamp <= window_end
    ]
    cpu_samples = [
        value
        for timestamp, value in load_test_results.cpu_by_time.items()
        if window_start <= timestamp <= window_end
    ]
    ram_samples = [
        value
        for timestamp, value in load_test_results.ram_by_time.items()
        if window_start <= timestamp <= window_end
    ]
    vram_samples = [
        value
        for timestamp, value in load_test_results.vram_by_time.items()
        if window_start <= timestamp <= window_end
    ]

    if not gpu_samples:
        raise RuntimeError("No GPU samples recorded during the steady ramp window.")
    if not cpu_samples:
        raise RuntimeError("No CPU samples recorded during the steady ramp window.")
    if not ram_samples:
        raise RuntimeError("No RAM samples recorded during the steady ramp window.")
    if not vram_samples:
        raise RuntimeError("No VRAM samples recorded during the steady ramp window.")

    return SystemUtilizationSummary(
        average_gpu_utilization_during_max_steady_ramp=_average(gpu_samples),
        average_cpu_utilization_during_max_steady_ramp=_average(cpu_samples),
        average_ram_utilization_during_max_steady_ramp=_average(ram_samples),
        average_vram_utilization_during_max_steady_ramp=_average(vram_samples),
    )


def _calculate_bucket_metrics(
    log_file: str,
    requests_per_second: int,
) -> list[BucketMetrics]:
    parsed = _parse_bucketed_series(log_file)
    clients_by_second = parsed["clients_by_second"]
    requests_by_second = parsed["requests_by_second"]
    errors_by_second = parsed["errors_by_second"]
    latencies_by_second = parsed["latencies_by_second"]
    total_seconds = int(parsed["full_seconds"])

    bucket_metrics: list[BucketMetrics] = []
    if total_seconds <= 0:
        return bucket_metrics

    bucket_index = 0
    second_idx = 0
    while second_idx < total_seconds:
        num_clients = int(clients_by_second[second_idx])
        run_start = second_idx
        while second_idx < total_seconds and int(clients_by_second[second_idx]) == num_clients:
            second_idx += 1
        run_end = second_idx

        seconds = range(run_start, run_end)
        total_requests = sum(int(requests_by_second[s]) for s in seconds)
        total_errors = sum(int(errors_by_second[s]) for s in seconds)
        success_count = total_requests - total_errors
        duration_sec = float(run_end - run_start)
        achieved_rps = (total_requests / duration_sec) if duration_sec > 0 else 0.0
        expected_rps = requests_per_second * num_clients
        success_rate = (success_count / total_requests) if total_requests else 0.0
        latency_samples = [lat for s in seconds for lat in latencies_by_second.get(s, [])]
        latency_p50 = _percentile(latency_samples, 0.5)
        latency_p95 = _percentile(latency_samples, 0.95)

        is_steady = (
            expected_rps > 0
            and achieved_rps >= expected_rps * STEADY_THROUGHPUT_RATIO
            and success_rate >= STEADY_SUCCESS_RATE
        )

        bucket_metrics.append(
            BucketMetrics(
                index=bucket_index,
                num_clients=num_clients,
                total_requests=total_requests,
                success_count=success_count,
                duration_sec=duration_sec,
                achieved_rps=achieved_rps,
                expected_rps=expected_rps,
                success_rate=success_rate,
                latency_p50=latency_p50,
                latency_p95=latency_p95,
                is_steady=is_steady,
            )
        )
        bucket_index += 1

    return bucket_metrics


def _average(values: list[float]) -> float:
    return sum(values) / len(values)


def plot_throughput_and_system_utilization_by_time(
    load_test_results: LoadTestResults,
    requests_per_second: int,
    output_dir: str,
    maximum_steady_rps: float | None = None,
):
    # Sort the latency data by time
    error_times, error_rate = zip(*sorted(load_test_results.errors_by_time.items()))
    request_times, request_rate = zip(*sorted(load_test_results.requests_by_time.items()))
    client_items = sorted(load_test_results.clients_by_time.items())
    client_times, num_clients = zip(*client_items) if client_items else ([], [])
    expected_response_rate = [requests_per_second * client_count for client_count in num_clients]

    # Calculate elapsed time in seconds
    start_time = load_test_results.start_time
    # Plot request/error values at the end of each 1-second bucket [t, t+1),
    # which avoids showing a visual ramp-up before the next target step.
    error_elapsed_seconds = [(time - start_time).total_seconds() + 1 for time in error_times]
    request_elapsed_seconds = [(time - start_time).total_seconds() + 1 for time in request_times]
    error_elapsed_seconds = [0.0, *error_elapsed_seconds]
    error_rate = [0, *error_rate]
    request_elapsed_seconds = [0.0, *request_elapsed_seconds]
    request_rate = [0, *request_rate]
    client_elapsed_seconds = [(time - start_time).total_seconds() for time in client_times]
    if client_elapsed_seconds:
        client_elapsed_seconds = [*client_elapsed_seconds, client_elapsed_seconds[-1] + 1.0]
        expected_response_rate = [*expected_response_rate, expected_response_rate[-1]]
    gpu_items = sorted(load_test_results.gpu_by_time.items())
    cpu_items = sorted(load_test_results.cpu_by_time.items())
    ram_items = sorted(load_test_results.ram_by_time.items())
    vram_items = sorted(load_test_results.vram_by_time.items())
    gpu_elapsed_seconds = [(time - start_time).total_seconds() for time, _ in gpu_items]
    gpu_utilization = [value for _, value in gpu_items]
    cpu_elapsed_seconds = [(time - start_time).total_seconds() for time, _ in cpu_items]
    cpu_utilization = [value for _, value in cpu_items]
    ram_elapsed_seconds = [(time - start_time).total_seconds() for time, _ in ram_items]
    ram_utilization = [value for _, value in ram_items]
    vram_elapsed_seconds = [(time - start_time).total_seconds() for time, _ in vram_items]
    vram_utilization = [value for _, value in vram_items]

    # Create the main plot
    fig, ax1 = plt.subplots(figsize=(10, 6))

    # Plot throughput and errors on the main y-axis
    ax1.plot(
        request_elapsed_seconds,
        request_rate,
        linestyle="-",
        color="green",
        label="Throughput",
        alpha=0.9,
        zorder=5,
    )
    ax1.plot(
        error_elapsed_seconds,
        error_rate,
        linestyle="-",
        color="red",
        label="Errors",
        alpha=0.9,
        zorder=3,
    )
    ax1.step(
        client_elapsed_seconds,
        expected_response_rate,
        where="post",
        color="black",
        label="Expected Requests / Num Clients",
        alpha=0.9,
        zorder=4,
    )
    ax1.set_xlabel("Elapsed Time (s)")
    ax1.set_ylabel("Total Requests / Second")
    ax1.grid(True)
    combined_rates = (*request_rate, *error_rate, *expected_response_rate)
    max_expected_requests = max(expected_response_rate) if expected_response_rate else 0
    max_requests = max_expected_requests or (max(combined_rates) if combined_rates else 0)
    ylim_upper = max_requests if max_requests else 1
    if maximum_steady_rps is not None:
        ylim_upper = max(ylim_upper, maximum_steady_rps)
    ax1.set_ylim((0, ylim_upper * 1.05))

    if maximum_steady_rps is not None:
        ax1.axhline(
            y=maximum_steady_rps,
            color="blue",
            linestyle="-",
            linewidth=1.5,
            label="Max Steady RPS",
            zorder=6,
        )

    # Create system utilization axis for CPU/GPU
    utilization_axis = None
    utilization_lines = []
    if gpu_elapsed_seconds or cpu_elapsed_seconds or ram_elapsed_seconds or vram_elapsed_seconds:
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
                zorder=2,
            )
            utilization_lines.append(gpu_line)
        if cpu_elapsed_seconds:
            (cpu_line,) = utilization_axis.plot(
                cpu_elapsed_seconds,
                cpu_utilization,
                color="teal",
                linestyle=":",
                label="CPU Utilization",
                zorder=2,
            )
            utilization_lines.append(cpu_line)
        if ram_elapsed_seconds:
            (ram_line,) = utilization_axis.plot(
                ram_elapsed_seconds,
                ram_utilization,
                color="brown",
                linestyle=":",
                label="RAM Utilization",
                zorder=2,
            )
            utilization_lines.append(ram_line)
        if vram_elapsed_seconds:
            (vram_line,) = utilization_axis.plot(
                vram_elapsed_seconds,
                vram_utilization,
                color="magenta",
                linestyle=":",
                label="VRAM Utilization",
                zorder=2,
            )
            utilization_lines.append(vram_line)
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
    client_axis.yaxis.set_major_locator(mticker.MaxNLocator(integer=True))

    # Set title and save the figure
    plt.title("Throughput and System Utilization Over Time")

    handle_by_label: dict[str, Any] = {}
    handles, labels = ax1.get_legend_handles_labels()
    for handle, label in zip(handles, labels):
        handle_by_label.setdefault(label, handle)
    if utilization_axis:
        util_handles, util_labels = utilization_axis.get_legend_handles_labels()
        for handle, label in zip(util_handles, util_labels):
            handle_by_label.setdefault(label, handle)

    legend_order = [
        "Expected Requests / Num Clients",
        "Throughput",
        "Errors",
        "Max Steady RPS",
        "GPU Utilization",
        "VRAM Utilization",
        "CPU Utilization",
        "RAM Utilization",
    ]
    ordered_handles = [handle_by_label[label] for label in legend_order if label in handle_by_label]
    ordered_labels = [label for label in legend_order if label in handle_by_label]
    ax1.legend(ordered_handles, ordered_labels, loc="upper left")

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


def plot_load_test_results(
    log_file: str,
    requests_per_second: int,
    output_dir: str,
    steady_rps: float | None = None,
) -> None:

    load_test_results = parse_log_file(log_file)
    plot_throughput_and_system_utilization_by_time(
        load_test_results,
        requests_per_second=requests_per_second,
        output_dir=output_dir,
        maximum_steady_rps=steady_rps,
    )
    plot_latency_over_time(
        load_test_results.average_latency_by_time,
        load_test_results.clients_by_time,
        load_test_results.start_time,
        output_dir=output_dir,
    )


def write_load_test_results_to_file(
    log_file: str,
    cli_args: Namespace,
    throughput_summary: ThroughputSummary,
    metadata: dict[str, Any],
    system_utilization_summary: SystemUtilizationSummary | None = None,
) -> str:
    """Persist CLI inputs, outputs, and metadata alongside the log file."""
    output_dir = os.path.dirname(os.path.abspath(log_file))
    os.makedirs(output_dir, exist_ok=True)

    model_dump = getattr(throughput_summary, "model_dump", None)
    summary_payload = model_dump() if callable(model_dump) else throughput_summary

    outputs: dict[str, Any] = {"throughput_summary": summary_payload}
    if system_utilization_summary is not None:
        outputs["system_utilization_summary"] = system_utilization_summary.model_dump()

    payload = {
        "inputs": vars(cli_args),
        "outputs": outputs,
        "metadata": metadata,
    }
    output_file = os.path.join(output_dir, "load_test_results.json")
    with open(output_file, "w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2)
    print(f"Load test results saved to: {output_file}")
    return output_file
