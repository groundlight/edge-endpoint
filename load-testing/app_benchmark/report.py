"""Aggregates metrics.csv + lens_events.csv into summary.json/md and plots."""

import csv
import json
import logging
import statistics
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from app_benchmark.config import BenchmarkConfig
from app_benchmark.detectors import CreatedDetector

logger = logging.getLogger(__name__)


def _percentiles(values: list[float], pcts: tuple[int, ...] = (50, 95, 99)) -> dict[str, float]:
    if not values:
        return {f"p{p}": 0.0 for p in pcts}
    sorted_vals = sorted(values)
    out: dict[str, float] = {}
    for p in pcts:
        idx = max(0, min(len(sorted_vals) - 1, int(p / 100 * (len(sorted_vals) - 1))))
        out[f"p{p}"] = float(sorted_vals[idx])
    return out


def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"p50": 0.0, "p95": 0.0, "mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0}
    sorted_vals = sorted(values)
    return {
        **_percentiles(values, (50, 95)),
        "mean": float(statistics.fmean(values)),
        "std": float(statistics.pstdev(values)) if len(values) > 1 else 0.0,
        "min": float(sorted_vals[0]),
        "max": float(sorted_vals[-1]),
    }


def _load_frame_events(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open() as f:
        reader = csv.DictReader(f)
        return [
            {
                "ts": float(row["ts"]),
                "lens_name": row["lens_name"],
                "client_id": row["client_id"],
                "stage_idx": int(row["stage_idx"]),
                "detector_id": row["detector_id"],
                "latency_ms": float(row["latency_ms"]),
                "http_status": int(row["http_status"]),
                "retry_count": int(row["retry_count"]),
                "was_terminal": bool(int(row["was_terminal"])),
                "composite_objects_count": int(row["composite_objects_count"]),
            }
            for row in reader
        ]


def _load_metrics(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open() as f:
        return [
            {
                "ts": float(row["ts"]),
                "cpu_total_pct": float(row["cpu_total_pct"]),
                "ram_used_bytes": int(row["ram_used_bytes"]),
                "ram_total_bytes": int(row["ram_total_bytes"]),
                "gpu_compute_total_pct": float(row["gpu_compute_total_pct"]),
                "gpu_vram_used_bytes": int(row["gpu_vram_used_bytes"]),
                "gpu_vram_total_bytes": int(row["gpu_vram_total_bytes"]),
                "loading_detectors_bytes": int(row["loading_detectors_bytes"]),
                "error": row["error"],
                "gpu_devices": row["gpu_devices"],
            }
            for row in csv.DictReader(f)
        ]


def _per_lens_summary(cfg: BenchmarkConfig, frame_events: list[dict],
                      run_started_ts: float, run_ended_ts: float) -> dict[str, dict]:
    """Aggregate stats per lens. FPS is counted from stage_idx == -1 rows ONLY."""
    out: dict[str, dict] = {}
    by_lens: dict[str, list[dict]] = defaultdict(list)
    for e in frame_events:
        by_lens[e["lens_name"]].append(e)

    duration_s = max(0.001, run_ended_ts - run_started_ts)

    for lens in cfg.lenses:
        events = by_lens.get(lens.name, [])
        frame_events_only = [e for e in events if e["stage_idx"] == -1]
        e2e_latencies = [e["latency_ms"] for e in frame_events_only]
        composite_counts = [e["composite_objects_count"] for e in frame_events_only]
        per_client_counts: dict[str, int] = defaultdict(int)
        for e in frame_events_only:
            per_client_counts[e["client_id"]] += 1

        achieved_fps_per_client = [
            {"client": cid, "fps": count / duration_s}
            for cid, count in sorted(per_client_counts.items())
        ]
        achieved_aggregate = len(frame_events_only) / duration_s

        # Error / retry rate from per-stage rows only.
        stage_rows = [e for e in events if e["stage_idx"] >= 0]
        if stage_rows:
            error_rate = sum(1 for e in stage_rows if e["http_status"] >= 400) / len(stage_rows) * 100
            retry_rate = sum(1 for e in stage_rows if e["retry_count"] > 0) / len(stage_rows) * 100
        else:
            error_rate = retry_rate = 0.0

        target_fps = lens.target_fps * lens.cameras
        fps_deficit = max(0.0, target_fps - achieved_aggregate) / target_fps * 100 if target_fps > 0 else 0.0

        status = "OK"
        if error_rate > lens.error_budget_pct:
            status = "DEGRADED"

        out[lens.name] = {
            "target_fps_per_camera": lens.target_fps,
            "cameras": lens.cameras,
            "image_resolution": list(lens.image.resolution),
            "downstream_crop_resolution": list(lens.downstream_crop.resize_to) if lens.downstream_crop else None,
            "status": status,
            "achieved_fps_aggregate": achieved_aggregate,
            "achieved_fps_per_client": achieved_fps_per_client,
            "e2e_latency_ms": _stats(e2e_latencies),
            "fps_deficit_pct": round(fps_deficit, 2),
            "error_rate_pct": round(error_rate, 3),
            "retry_rate_pct": round(retry_rate, 3),
            "composite_objects_count": _stats(composite_counts) if composite_counts else None,
            "frame_count": len(frame_events_only),
        }
    return out


def _system_summary(metrics: list[dict]) -> dict[str, Any]:
    if not metrics:
        return {}
    cpu = [m["cpu_total_pct"] for m in metrics]
    ram_used = [m["ram_used_bytes"] for m in metrics]
    gpu_compute = [m["gpu_compute_total_pct"] for m in metrics]
    vram_used = [m["gpu_vram_used_bytes"] for m in metrics]

    per_device: dict[int, list[dict]] = defaultdict(list)
    for m in metrics:
        if not m["gpu_devices"]:
            continue
        for d in m["gpu_devices"].split("|"):
            parts = d.split(":")
            if len(parts) < 6:
                continue
            try:
                idx = int(parts[0])
                per_device[idx].append({
                    "name": parts[1],
                    "vram_used": int(parts[2]),
                    "vram_total": int(parts[3]),
                    "compute_pct": float(parts[4]),
                    "memory_bandwidth_pct": float(parts[5]),
                })
            except ValueError:
                continue

    devices_summary = []
    for idx in sorted(per_device.keys()):
        rows = per_device[idx]
        devices_summary.append({
            "index": idx,
            "name": rows[0]["name"],
            "vram_used_bytes": _stats([r["vram_used"] for r in rows]),
            "compute_pct": _stats([r["compute_pct"] for r in rows]),
            "memory_bandwidth_pct": _stats([r["memory_bandwidth_pct"] for r in rows]),
        })

    if len(devices_summary) > 1:
        peaks = [d["vram_used_bytes"]["max"] for d in devices_summary]
        max_peak = max(peaks)
        min_peak = min(peaks)
        imbalance = (max_peak - min_peak) / max_peak * 100 if max_peak else 0.0
    else:
        imbalance = 0.0

    return {
        "cpu_total_pct": _stats(cpu),
        "ram_used_bytes": _stats(ram_used),
        "gpu_compute_total_pct": _stats(gpu_compute),
        "gpu_vram_used_bytes": _stats(vram_used),
        "vram_imbalance_pct": round(imbalance, 2),
        "gpu_per_device": devices_summary,
    }


def _plot_fps_per_lens(cfg: BenchmarkConfig, frame_events: list[dict], out_path: Path) -> None:
    by_lens: dict[str, list[dict]] = defaultdict(list)
    for e in frame_events:
        if e["stage_idx"] == -1:
            by_lens[e["lens_name"]].append(e)

    lens_names = [l.name for l in cfg.lenses]
    n = max(1, len(lens_names))
    fig, axes = plt.subplots(n, 1, figsize=(10, 3.0 * n), sharex=True, squeeze=False)
    for i, lens_name in enumerate(lens_names):
        ax = axes[i][0]
        events = sorted(by_lens.get(lens_name, []), key=lambda e: e["ts"])
        if not events:
            ax.set_title(f"{lens_name} (no events)")
            continue
        t0 = events[0]["ts"]
        # Per-second FPS bins.
        bins: dict[int, int] = defaultdict(int)
        for e in events:
            bins[int(e["ts"] - t0)] += 1
        xs = sorted(bins.keys())
        ys = [bins[x] for x in xs]
        ax.plot(xs, ys, label="FPS (frames/sec)", color="C0")
        ax.set_ylabel("FPS", color="C0")
        ax.set_title(lens_name)

        # Overlay composite objects count if chained.
        lens_obj = next((l for l in cfg.lenses if l.name == lens_name), None)
        if lens_obj and len(lens_obj.chain) > 1:
            ax2 = ax.twinx()
            xs_obj = [e["ts"] - t0 for e in events]
            ys_obj = [e["composite_objects_count"] for e in events]
            ax2.plot(xs_obj, ys_obj, label="composite_objects_count", color="C3", alpha=0.4, linewidth=0.7)
            ax2.set_ylabel("# objects", color="C3")
            ax2.set_ylim(bottom=0)

    axes[-1][0].set_xlabel("seconds since first frame")
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def _plot_fps_combined(cfg: BenchmarkConfig, frame_events: list[dict], out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 5))
    by_lens: dict[str, list[dict]] = defaultdict(list)
    for e in frame_events:
        if e["stage_idx"] == -1:
            by_lens[e["lens_name"]].append(e)

    if not by_lens:
        ax.text(0.5, 0.5, "no frame events", ha="center", va="center", transform=ax.transAxes)
    else:
        all_starts = [min(e["ts"] for e in evs) for evs in by_lens.values()]
        t0 = min(all_starts)
        for lens_name in [l.name for l in cfg.lenses]:
            events = sorted(by_lens.get(lens_name, []), key=lambda e: e["ts"])
            if not events:
                continue
            bins: dict[int, int] = defaultdict(int)
            for e in events:
                bins[int(e["ts"] - t0)] += 1
            xs = sorted(bins.keys())
            ys = [bins[x] for x in xs]
            ax.plot(xs, ys, label=lens_name, alpha=0.85)

    ax.set_xlabel("seconds since run start")
    ax.set_ylabel("frames/sec (lens-loop iterations)")
    ax.set_title("FPS per lens (cross-lens contention view)")
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


_BYTES_PER_GB = 1024 ** 3


def _plot_system_metric(
    metrics: list[dict],
    field: str,
    label: str,
    out_path: Path,
    *,
    bytes_to_gb: bool = False,
) -> None:
    fig, ax = plt.subplots(figsize=(10, 4))
    if not metrics:
        ax.text(0.5, 0.5, "no samples", ha="center", va="center", transform=ax.transAxes)
    else:
        t0 = metrics[0]["ts"]
        xs = [m["ts"] - t0 for m in metrics]
        ys = [m[field] for m in metrics]
        if bytes_to_gb:
            ys = [y / _BYTES_PER_GB for y in ys]
        ax.plot(xs, ys, color="C2")
    ax.set_xlabel("seconds")
    ax.set_ylabel(label)
    ax.set_title(label)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def _write_summary_md(summary: dict[str, Any], out_path: Path) -> None:
    lines: list[str] = []
    lines.append(f"# Benchmark Summary: {summary['run_name']}")
    lines.append("")
    lines.append(f"Status: **{summary['run_status']}**  ")
    lines.append(f"Duration: {summary['duration_seconds']}s (warmup {summary['warmup']['duration_seconds']}s, "
                 f"steady_state_reached={summary['warmup']['steady_state_reached']})  ")
    lines.append(f"Started: {summary['started_at_iso']}")
    nl = (summary.get("environment") or {}).get("network_latency_ms")
    if nl:
        lines.append(
            f"Network latency to edge ({nl['count']} pings to {nl['host']}): "
            f"min/avg/max/stddev = "
            f"{nl['min_ms']:.3f}/{nl['avg_ms']:.3f}/{nl['max_ms']:.3f}/{nl['stddev_ms']:.3f} ms"
        )
    lines.append("")
    lines.append("## Lenses")
    lines.append("")
    lines.append("| Lens | Status | Aggregate FPS | Target FPS | Deficit % | E2E p50 (ms) | E2E p95 (ms) | Errors % |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for name, lens in summary.get("lenses", {}).items():
        target = lens["target_fps_per_camera"] * lens["cameras"]
        lines.append(
            f"| {name} | **{lens['status']}** | {lens['achieved_fps_aggregate']:.2f} | {target:.2f} | "
            f"{lens['fps_deficit_pct']:.1f} | {lens['e2e_latency_ms']['p50']:.1f} | "
            f"{lens['e2e_latency_ms']['p95']:.1f} | {lens['error_rate_pct']:.2f} |"
        )

    sys_sum = summary.get("system", {}) or {}
    if sys_sum:
        lines.append("")
        lines.append("## System")
        lines.append("")
        cpu = sys_sum.get("cpu_total_pct", {})
        ram = sys_sum.get("ram_used_bytes", {})
        gpu = sys_sum.get("gpu_compute_total_pct", {})
        vram = sys_sum.get("gpu_vram_used_bytes", {})
        gb = _BYTES_PER_GB
        lines.append(f"- CPU total: p50={cpu.get('p50', 0):.1f}%, p95={cpu.get('p95', 0):.1f}%")
        lines.append(f"- RAM used: p50={ram.get('p50', 0)/gb:.2f} GB, p95={ram.get('p95', 0)/gb:.2f} GB")
        lines.append(f"- GPU compute: p50={gpu.get('p50', 0):.1f}%, p95={gpu.get('p95', 0):.1f}%")
        lines.append(f"- GPU VRAM used: p50={vram.get('p50', 0)/gb:.2f} GB, p95={vram.get('p95', 0)/gb:.2f} GB")
        lines.append(f"- VRAM imbalance: {sys_sum.get('vram_imbalance_pct', 0):.1f}%")

    warnings: list[str] = []
    for name, lens in summary.get("lenses", {}).items():
        if lens["fps_deficit_pct"] > 5:
            warnings.append(f"**WARNING**: {name} FPS deficit {lens['fps_deficit_pct']:.1f}% (target not met)")
        if lens["error_rate_pct"] > 0:
            warnings.append(f"**WARNING**: {name} HTTP error rate {lens['error_rate_pct']:.2f}%")
    if sys_sum.get("vram_imbalance_pct", 0) > 30:
        warnings.append(f"**WARNING**: multi-GPU VRAM imbalance {sys_sum['vram_imbalance_pct']:.1f}%")
    if warnings:
        lines.append("")
        lines.append("## Warnings")
        lines.append("")
        for w in warnings:
            lines.append(f"- {w}")

    out_path.write_text("\n".join(lines) + "\n")


def build(
    cfg: BenchmarkConfig,
    output_dir: Path,
    *,
    run_name: str,
    started_at_iso: str,
    run_started_ts: float,
    run_ended_ts: float,
    warmup_duration_s: float,
    steady_state_reached: bool,
    run_status: str,
    config_hash: str,
    environment: dict[str, Any],
    control_plane: dict[str, Any],
    run_warnings: dict[str, Any],
    created: list[CreatedDetector],
) -> Path:
    """Aggregates artifacts into output_dir/. Returns path to summary.json."""
    plots_dir = output_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    frame_events = _load_frame_events(output_dir / "lens_events.csv")
    metrics = _load_metrics(output_dir / "metrics.csv")

    lens_summary = _per_lens_summary(cfg, frame_events, run_started_ts, run_ended_ts)
    system_summary = _system_summary(metrics)

    summary: dict[str, Any] = {
        "schema_version": 1,
        "run_name": run_name,
        "run_status": run_status,
        "config_hash": config_hash,
        "started_at_iso": started_at_iso,
        "duration_seconds": int(run_ended_ts - run_started_ts),
        "warmup": {
            "duration_seconds": int(warmup_duration_s),
            "steady_state_reached": steady_state_reached,
        },
        "environment": environment,
        "lenses": lens_summary,
        "system": system_summary,
        "control_plane": control_plane,
        "run_warnings": run_warnings,
        "detectors": [{"spec_name": c.spec_name, "detector_id": c.detector_id} for c in created],
    }

    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str))

    _write_summary_md(summary, output_dir / "summary.md")

    _plot_fps_per_lens(cfg, frame_events, plots_dir / "fps_per_lens.png")
    _plot_fps_combined(cfg, frame_events, plots_dir / "fps_combined.png")
    _plot_system_metric(metrics, "cpu_total_pct", "CPU total %", plots_dir / "cpu.png")
    _plot_system_metric(metrics, "ram_used_bytes", "RAM used (GB)",
                        plots_dir / "ram.png", bytes_to_gb=True)
    _plot_system_metric(metrics, "gpu_compute_total_pct", "GPU compute %",
                        plots_dir / "gpu_compute.png")
    _plot_system_metric(metrics, "gpu_vram_used_bytes", "VRAM used (GB)",
                        plots_dir / "vram.png", bytes_to_gb=True)

    logger.info("report written to %s", output_dir, extra={"phase": "report"})
    return summary_path
