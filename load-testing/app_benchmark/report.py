"""Per-run + cross-run summaries and plots from the JSONL request log.

Output layout under each benchmark's output_dir:

    summary.md          ← single consolidated doc (overview + per-run sections)
    summary.json        ← cross-run machine-readable
    run_NN/
        load_test.log
        summary.json    ← per-run machine-readable
        plots/
            fps_{lens}_camera_{N}.png
            system_utilization.png   ← 2x2 grid: CPU%, GPU%, RAM GB, VRAM GB

Everything is plotted on a benchmark-relative time axis (seconds since the
post-warmup main start) so plots line up across cameras and resources.
"""

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt

# Achieved FPS counts as "hit" target if it's within this fraction.
_FPS_HIT_TOLERANCE = 0.95


def _read_request_events(log_file: Path, start_ts: float) -> list[dict]:
    out: list[dict] = []
    with log_file.open() as f:
        for line in f:
            line = line.strip()
            if not line.startswith("{"):
                continue
            payload = json.loads(line)
            if payload.get("event") != "request":
                continue
            if float(payload.get("ts", 0)) < start_ts:
                continue
            out.append(payload)
    return out


def _read_resource_events(log_file: Path, main_start_ts: float) -> dict[str, Any]:
    """Bucket cpu/gpu events by seconds-since-main-start. Returns dicts of
    {seconds_offset: value} plus discovered totals (max seen)."""
    cpu_pct: dict[float, float] = {}
    ram_gb: dict[float, float] = {}
    gpu_pct: dict[float, float] = {}
    vram_gb: dict[float, float] = {}
    ram_total = 0.0
    vram_total = 0.0
    with log_file.open() as f:
        for line in f:
            line = line.strip()
            if not line.startswith("{"):
                continue
            payload = json.loads(line)
            event = payload.get("event")
            if event not in ("cpu", "gpu"):
                continue
            offset = float(payload.get("ts", 0)) - main_start_ts
            if offset < 0:
                continue
            if event == "cpu":
                cpu_pct[offset] = float(payload.get("cpu_percent", 0))
                ram_gb[offset] = float(payload.get("ram_used_gb", 0))
                ram_total = max(ram_total, float(payload.get("ram_total_gb", 0)))
            else:
                gpu_pct[offset] = float(payload.get("gpu_utilization", 0))
                vram_gb[offset] = float(payload.get("vram_used_gb", 0))
                vram_total = max(vram_total, float(payload.get("vram_total_gb", 0)))
    return {
        "cpu_pct": cpu_pct, "gpu_pct": gpu_pct,
        "ram_gb": ram_gb, "ram_total_gb": ram_total,
        "vram_gb": vram_gb, "vram_total_gb": vram_total,
    }


def _is_frame(event: dict) -> bool:
    """A frame = one lens-loop iteration. For multi-stage lenses only the
    upstream `bbox` event counts; single-stage lenses have no `stage` field."""
    return "stage" not in event or event.get("stage") == "bbox"


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, int(pct * len(sorted_values)))
    return sorted_values[idx]


def _summarize(events: list[dict], target_fps: float | None) -> dict[str, Any]:
    frames = [e for e in events if _is_frame(e)]
    total_frames = len(frames)
    errors = sum(1 for e in events if not e.get("success", True))
    latencies = sorted(float(e.get("latency", 0)) for e in events)
    duration = 0.0
    if events:
        ts = [float(e["ts"]) for e in events]
        duration = max(ts) - min(ts)
    achieved_fps = total_frames / duration if duration > 0 else 0.0

    if target_fps is None or target_fps <= 0:
        hit = None
    else:
        hit = achieved_fps >= target_fps * _FPS_HIT_TOLERANCE

    return {
        "total_frames": total_frames,
        "total_requests": len(events),
        "errors": errors,
        "duration_seconds": round(duration, 2),
        "achieved_fps": round(achieved_fps, 2),
        "target_fps": target_fps,
        "hit_target": hit,
        "latency_p50_sec": round(_percentile(latencies, 0.5), 4),
        "latency_p95_sec": round(_percentile(latencies, 0.95), 4),
    }


def write_run_artifacts(
    run_dir: Path,
    log_file: Path,
    run_meta: dict[str, Any],
    main_start_ts: float,
) -> dict[str, Any]:
    """Per-(lens, camera) stats + FPS plots + 2x2 system grid. Writes
    summary.json (machine-readable) but NOT summary.md — top-level
    write_top_level produces a single consolidated doc."""
    events = _read_request_events(log_file, start_ts=main_start_ts)
    target_by_lens: dict[str, float] = {l["name"]: l["target_fps"] for l in run_meta["lenses"]}
    by_camera: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for ev in events:
        key = (ev.get("lens_name", "_"), int(ev.get("camera", 0)))
        by_camera[key].append(ev)

    cameras_summary: list[dict[str, Any]] = []
    for (lens_name, camera), camera_events in sorted(by_camera.items()):
        stats = _summarize(camera_events, target_by_lens.get(lens_name))
        stats["lens_name"] = lens_name
        stats["camera"] = camera
        cameras_summary.append(stats)

    summary = {
        "meta": run_meta,
        "cameras": cameras_summary,
        "aggregate": _summarize(events, target_fps=None),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    _plot_run(run_dir, by_camera, target_by_lens, main_start_ts, log_file)
    return summary


def _plot_run(
    run_dir: Path,
    by_camera: dict[tuple[str, int], list[dict]],
    target_by_lens: dict[str, float],
    main_start_ts: float,
    log_file: Path,
) -> None:
    plots_dir = run_dir / "plots"
    plots_dir.mkdir(exist_ok=True)
    for (lens_name, camera), events in sorted(by_camera.items()):
        _plot_camera_fps(plots_dir, lens_name, camera, events,
                         target_by_lens.get(lens_name), main_start_ts)
    _plot_system_grid(plots_dir, log_file, main_start_ts)


def _plot_camera_fps(
    plots_dir: Path,
    lens_name: str,
    camera: int,
    events: list[dict],
    target_fps: float | None,
    main_start_ts: float,
) -> None:
    buckets: dict[int, int] = defaultdict(int)
    for ev in events:
        if not _is_frame(ev):
            continue
        sec = int(float(ev["ts"]) - main_start_ts)
        buckets[sec] += 1
    if not buckets:
        return
    seconds = sorted(buckets.keys())
    fps_values = [buckets[s] for s in seconds]

    fig, ax = plt.subplots(figsize=(9, 3.5))
    ax.plot(seconds, fps_values, color="tab:blue",
            marker="o", markersize=3, linewidth=1.2,
            label=f"{lens_name} cam {camera}")
    if target_fps is not None and target_fps > 0:
        ax.axhline(target_fps, color="tab:red", linestyle="--", alpha=0.7,
                   label=f"target {target_fps:.1f} fps")
    ax.set_title(f"{lens_name} — camera {camera} — FPS over time")
    ax.set_xlabel("seconds since main start")
    ax.set_ylabel("frames per second")
    ax.set_ylim(bottom=0)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(plots_dir / f"fps_{lens_name}_camera_{camera}.png", dpi=120)
    plt.close(fig)


def _plot_system_grid(plots_dir: Path, log_file: Path, main_start_ts: float) -> None:
    parsed = _read_resource_events(log_file, main_start_ts)
    has_any = any((parsed["cpu_pct"], parsed["gpu_pct"], parsed["ram_gb"], parsed["vram_gb"]))
    if not has_any:
        return

    fig, axes = plt.subplots(2, 2, figsize=(12, 7), sharex=True)
    cpu_ax, gpu_ax = axes[0]
    ram_ax, vram_ax = axes[1]

    _plot_pct(cpu_ax, parsed["cpu_pct"], "CPU utilization", color="tab:blue")
    _plot_pct(gpu_ax, parsed["gpu_pct"], "GPU compute utilization", color="tab:red")
    _plot_gb(ram_ax, parsed["ram_gb"], parsed["ram_total_gb"], "RAM used", color="tab:green")
    _plot_gb(vram_ax, parsed["vram_gb"], parsed["vram_total_gb"], "VRAM used", color="tab:purple")

    for ax in axes.flat:
        ax.set_xlabel("seconds since main start")
        ax.grid(True, alpha=0.3)
    fig.suptitle("System utilization", fontsize=14)
    fig.tight_layout()
    fig.savefig(plots_dir / "system_utilization.png", dpi=120)
    plt.close(fig)


def _plot_pct(ax, series: dict[float, float], title: str, color: str) -> None:
    items = sorted(series.items())
    if items:
        ax.plot([t for t, _ in items], [v for _, v in items], color=color, linewidth=1.2)
    ax.set_title(title)
    ax.set_ylabel("%")
    ax.set_ylim(0, 105)


def _plot_gb(ax, series: dict[float, float], total_gb: float, title: str, color: str) -> None:
    items = sorted(series.items())
    if items:
        ax.plot([t for t, _ in items], [v for _, v in items], color=color, linewidth=1.2)
    if total_gb > 0:
        ax.axhline(total_gb, color="gray", linestyle="--", alpha=0.5,
                   label=f"total {total_gb:.1f} GB")
        ax.legend(loc="lower right")
    ax.set_title(title)
    ax.set_ylabel("GB")
    ax.set_ylim(bottom=0)


# ---------------------------------------------------------------------------
# Top-level consolidated summary
# ---------------------------------------------------------------------------


def _hit_label(hit: bool | None) -> str:
    if hit is None:
        return "—"
    return "yes" if hit else "no"


def _target_label(target_fps: float | None) -> str:
    if target_fps is None:
        return "—"
    if target_fps <= 0:
        return "saturate"
    return f"{target_fps:.1f}"


def write_top_level(
    out_root: Path,
    summaries: list[dict[str, Any]],
    *,
    benchmark_meta: dict[str, Any],
    network_baseline: dict | None,
    network_baseline_text: str,
) -> None:
    """Single consolidated summary.md with environment block, cross-run
    overview, and one section per run (table + plots)."""
    payload = {
        "meta": benchmark_meta,
        "network_baseline": network_baseline,
        "runs": summaries,
    }
    (out_root / "summary.json").write_text(json.dumps(payload, indent=2))

    lines = [f"# Benchmark: {benchmark_meta.get('name', '?')}", ""]
    lines.append(f"- **Started**: {benchmark_meta.get('started_at', '?')}")
    lines.append(f"- **Edge endpoint**: `{benchmark_meta.get('edge_endpoint_url', '?')}`")
    lines.append(f"- **Network ping baseline**: {network_baseline_text}")
    cfg = benchmark_meta.get("config", {})
    if cfg:
        lines.append(
            f"- **Defaults**: image_size `{cfg.get('image_size')}`, "
            f"target_fps `{cfg.get('target_fps')}`, "
            f"duration `{cfg.get('duration_seconds')}s`, "
            f"warmup `{cfg.get('warmup_seconds')}s`"
        )
    lines.append("")

    if not summaries:
        lines.append("(no runs)")
        (out_root / "summary.md").write_text("\n".join(lines) + "\n")
        return

    lines.append("## Overview")
    lines.append("")
    lens_names = sorted({c["lens_name"] for s in summaries for c in s.get("cameras", [])})
    per_lens_cols = [c for lens in lens_names for c in (f"{lens} FPS", f"{lens} Hit")]
    lines.append(
        f"Per-lens FPS = mean across that lens's camera processes. "
        f"Hit = `yes` if every camera hit ≥{int(_FPS_HIT_TOLERANCE * 100)}% of its target."
    )
    lines.append("")
    header = ["run", "lens_n"] + per_lens_cols
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")
    for s in summaries:
        meta = s["meta"]
        cells = [str(meta.get("run_index", "?")), f"`{meta.get('lens_n', {})}`"]
        cams_by_lens: dict[str, list[dict]] = defaultdict(list)
        for cam in s.get("cameras", []):
            cams_by_lens[cam["lens_name"]].append(cam)
        for lens in lens_names:
            cams = cams_by_lens.get(lens, [])
            if not cams:
                cells.extend(["—", "—"])
                continue
            mean_fps = sum(c["achieved_fps"] for c in cams) / len(cams)
            hits = [c["hit_target"] for c in cams]
            if all(h is None for h in hits):
                hit = "—"
            elif any(h is False for h in hits):
                hit = "no"
            else:
                hit = "yes"
            cells.append(f"{mean_fps:.1f}")
            cells.append(hit)
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    for s in summaries:
        lines.extend(_render_run_section(s))

    (out_root / "summary.md").write_text("\n".join(lines) + "\n")


def _render_run_section(s: dict[str, Any]) -> list[str]:
    meta = s["meta"]
    run_index = meta.get("run_index", "?")
    run_dir = f"run_{int(run_index):02d}" if isinstance(run_index, int) else f"run_{run_index}"
    lines = [
        f"## Run {run_index}",
        "",
        f"- **lens_n**: `{meta.get('lens_n', {})}`",
        f"- **duration**: `{meta.get('duration_seconds')}s`  "
        f"**warmup**: `{meta.get('warmup_seconds')}s`",
        "",
        "| Lens | Camera | Frames | Errors | FPS | Target | Hit | p50 (s) | p95 (s) |",
        "|---|---:|---:|---:|---:|---:|:---:|---:|---:|",
    ]
    for cam in s.get("cameras", []):
        lines.append(
            f"| {cam['lens_name']} | {cam['camera']} | {cam['total_frames']} | "
            f"{cam['errors']} | {cam['achieved_fps']:.1f} | "
            f"{_target_label(cam['target_fps'])} | {_hit_label(cam['hit_target'])} | "
            f"{cam['latency_p50_sec']:.3f} | {cam['latency_p95_sec']:.3f} |"
        )
    lines.append("")
    lines.append(f"![system utilization]({run_dir}/plots/system_utilization.png)")
    lines.append("")
    lines.append("**FPS plots:**")
    for cam in s.get("cameras", []):
        fname = f"fps_{cam['lens_name']}_camera_{cam['camera']}.png"
        lines.append(f"- [{cam['lens_name']} cam {cam['camera']}]({run_dir}/plots/{fname})")
    lines.append("")
    return lines
