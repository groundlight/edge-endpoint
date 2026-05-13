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
from parse_load_test_logs import _percentile as _interp_percentile

# Achieved FPS counts as "hit" target if it's within this fraction.
_FPS_HIT_TOLERANCE = 0.95


def _read_request_events(log_file: Path, start_ts: float, end_ts: float) -> list[dict]:
    out: list[dict] = []
    with log_file.open() as f:
        for line in f:
            line = line.strip()
            if not line.startswith("{"):
                continue
            payload = json.loads(line)
            if payload.get("event") != "request":
                continue
            ts = float(payload.get("ts", 0))
            if ts < start_ts or ts >= end_ts:
                continue
            out.append(payload)
    return out


def _read_resource_events(log_file: Path, start_ts: float, end_ts: float) -> dict[str, Any]:
    """Bucket cpu/gpu events by seconds-since-start_ts within [start, end).
    Returns dicts of {seconds_offset: value} plus discovered totals."""
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
            ts = float(payload.get("ts", 0))
            if ts < start_ts or ts >= end_ts:
                continue
            offset = ts - start_ts
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


def _summarize(events: list[dict], target_fps: float | None, duration_s: float) -> dict[str, Any]:
    """Summarize events over a FIXED window of `duration_s` seconds. FPS
    is computed against that fixed duration, not against max-min of the
    observed event timestamps — so in-flight or grace-period stragglers
    can't drag duration up and FPS down."""
    frames = [e for e in events if _is_frame(e)]
    total_frames = len(frames)
    errors = sum(1 for e in events if not e.get("success", True))
    latencies = sorted(float(e.get("latency", 0)) for e in events)
    achieved_fps = total_frames / duration_s if duration_s > 0 else 0.0

    if target_fps is None or target_fps <= 0:
        hit = None
    else:
        hit = achieved_fps >= target_fps * _FPS_HIT_TOLERANCE

    return {
        "total_frames": total_frames,
        "total_requests": len(events),
        "errors": errors,
        "duration_seconds": round(duration_s, 2),
        "achieved_fps": round(achieved_fps, 2),
        "target_fps": target_fps,
        "hit_target": hit,
        "latency_p50_sec": round(_interp_percentile(latencies, 0.5), 4),
        "latency_p95_sec": round(_interp_percentile(latencies, 0.95), 4),
    }


def write_run_artifacts(
    run_dir: Path,
    log_file: Path,
    run_meta: dict[str, Any],
    *,
    main_start_ts: float,
    main_end_ts: float,
) -> dict[str, Any]:
    """Per-(lens, camera) stats + FPS plots + 2x2 system grid. Writes
    summary.json (machine-readable) but NOT summary.md — top-level
    write_top_level produces a single consolidated doc."""
    duration_s = main_end_ts - main_start_ts
    events = _read_request_events(log_file, start_ts=main_start_ts, end_ts=main_end_ts)
    target_by_lens: dict[str, float] = {l["name"]: l["target_fps"] for l in run_meta["lenses"]}
    by_camera: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for ev in events:
        key = (ev.get("lens_name", "_"), int(ev.get("camera", 0)))
        by_camera[key].append(ev)

    # Expected (lens, camera) set from config — emit rows for missing ones too.
    expected_cameras: list[tuple[str, int]] = []
    for lens in run_meta["lenses"]:
        for cam_idx in range(int(lens["cameras"])):
            expected_cameras.append((lens["name"], cam_idx))

    cameras_summary: list[dict[str, Any]] = []
    for (lens_name, camera) in expected_cameras:
        camera_events = by_camera.get((lens_name, camera), [])
        stats = _summarize(camera_events, target_by_lens.get(lens_name), duration_s)
        stats["lens_name"] = lens_name
        stats["camera"] = camera
        # If no events were observed for an expected camera, that worker
        # almost certainly crashed before its first request — flag it loudly
        # and override Hit to False so the run-level verdict reflects it.
        if not camera_events:
            stats["no_events"] = True
            if stats["target_fps"] is not None and stats["target_fps"] > 0:
                stats["hit_target"] = False
        cameras_summary.append(stats)

    summary = {
        "meta": run_meta,
        "cameras": cameras_summary,
        "aggregate": _summarize(events, target_fps=None, duration_s=duration_s),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    _plot_run(run_dir, by_camera, target_by_lens, main_start_ts, main_end_ts, log_file)
    return summary


def _plot_run(
    run_dir: Path,
    by_camera: dict[tuple[str, int], list[dict]],
    target_by_lens: dict[str, float],
    main_start_ts: float,
    main_end_ts: float,
    log_file: Path,
) -> None:
    plots_dir = run_dir / "plots"
    plots_dir.mkdir(exist_ok=True)
    for (lens_name, camera), events in sorted(by_camera.items()):
        _plot_camera_fps(plots_dir, lens_name, camera, events,
                         target_by_lens.get(lens_name), main_start_ts)
    _plot_system_grid(plots_dir, log_file, main_start_ts, main_end_ts)


def _plot_camera_fps(
    plots_dir: Path,
    lens_name: str,
    camera: int,
    events: list[dict],
    target_fps: float | None,
    main_start_ts: float,
) -> None:
    fps_buckets: dict[int, int] = defaultdict(int)
    err_buckets: dict[int, int] = defaultdict(int)
    for ev in events:
        sec = int(float(ev["ts"]) - main_start_ts)
        if _is_frame(ev):
            fps_buckets[sec] += 1
        if not ev.get("success", True):
            err_buckets[sec] += 1
    if not fps_buckets:
        return
    seconds = sorted(fps_buckets.keys())
    fps_values = [fps_buckets[s] for s in seconds]

    fig, ax = plt.subplots(figsize=(9, 4.0))
    line_fps, = ax.plot(seconds, fps_values, color="tab:blue",
                        marker="o", markersize=3, linewidth=1.2, label="FPS")
    handles: list = [line_fps]
    if target_fps is not None and target_fps > 0:
        line_target = ax.axhline(target_fps, color="tab:orange", linestyle="--", alpha=0.8,
                                 label=f"target {target_fps:.1f} fps")
        handles.append(line_target)
    ax.set_title(f"{lens_name} — camera {camera} — FPS over time")
    ax.set_xlabel("seconds since main start")
    ax.set_ylabel("frames per second", color="tab:blue")
    ax.tick_params(axis="y", labelcolor="tab:blue")
    ax.set_ylim(bottom=0)
    ax.grid(True, alpha=0.3)

    ax_err = ax.twinx()
    err_seconds = sorted(set(seconds) | set(err_buckets.keys()))
    err_values = [err_buckets.get(s, 0) for s in err_seconds]
    line_err, = ax_err.plot(err_seconds, err_values, color="tab:red",
                            linewidth=1.2, label="failed requests / sec")
    ax_err.set_ylabel("failed requests / sec", color="tab:red")
    ax_err.tick_params(axis="y", labelcolor="tab:red")
    ax_err.set_ylim(bottom=0)
    handles.append(line_err)

    ax.legend(handles=handles, loc="lower right")
    fig.tight_layout()
    fig.savefig(plots_dir / f"fps_{lens_name}_camera_{camera}.png", dpi=120)
    plt.close(fig)


def _plot_system_grid(plots_dir: Path, log_file: Path, main_start_ts: float, main_end_ts: float) -> None:
    parsed = _read_resource_events(log_file, main_start_ts, main_end_ts)
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
    overview, combined cross-run plots, and one section per run.

    Combined plots span all runs on a benchmark-wall-clock time axis with
    vertical lines at each run boundary. Per-run plots remain in
    run_NN/plots/ for drill-down.
    """
    payload = {
        "meta": benchmark_meta,
        "network_baseline": network_baseline,
        "runs": summaries,
    }
    (out_root / "summary.json").write_text(json.dumps(payload, indent=2))

    plot_refs: dict[str, Any] = {}
    if summaries:
        plot_refs = _write_combined_plots(out_root, summaries)

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

    if plot_refs.get("system"):
        lines.append("## Cross-run system utilization")
        lines.append("")
        lines.append(f"![system utilization]({plot_refs['system']})")
        lines.append("")

    if plot_refs.get("fps_per_camera"):
        lines.append("## Cross-run FPS per camera")
        lines.append("")
        for (lens, camera), rel_path in plot_refs["fps_per_camera"]:
            lines.append(f"### {lens} — camera {camera}")
            lines.append("")
            lines.append(f"![{lens} cam {camera}]({rel_path})")
            lines.append("")

    lines.append("## Run details")
    lines.append("")
    lines.append(
        "Per-run plots (one system_utilization.png and one fps_*.png per camera) "
        "live under each `run_NN/plots/` directory."
    )
    lines.append("")
    for s in summaries:
        lines.extend(_render_run_section(s))

    (out_root / "summary.md").write_text("\n".join(lines) + "\n")


def _render_run_section(s: dict[str, Any]) -> list[str]:
    meta = s["meta"]
    run_index = meta.get("run_index", "?")
    lines = [
        f"### Run {run_index}",
        "",
        f"- **lens_n**: `{meta.get('lens_n', {})}`",
        f"- **duration**: `{meta.get('duration_seconds')}s`  "
        f"**warmup**: `{meta.get('warmup_seconds')}s`",
    ]
    failures = meta.get("worker_failures") or []
    if failures:
        lines.append("")
        lines.append(
            f"> ⚠ **{len(failures)} worker process(es) exited with non-zero status**: "
            + ", ".join(f"`{f['name']}` (exit={f['exitcode']})" for f in failures)
        )
    lines.append("")
    lines.append("| Lens | Camera | Frames | Errors | FPS | Target | Hit | p50 (s) | p95 (s) |")
    lines.append("|---|---:|---:|---:|---:|---:|:---:|---:|---:|")
    for cam in s.get("cameras", []):
        if cam.get("no_events"):
            lines.append(
                f"| {cam['lens_name']} | {cam['camera']} | 0 | ? | 0.0 | "
                f"{_target_label(cam['target_fps'])} | {_hit_label(cam['hit_target'])} | "
                f"— | — |  ⚠ no events captured (worker likely crashed)"
            )
            continue
        lines.append(
            f"| {cam['lens_name']} | {cam['camera']} | {cam['total_frames']} | "
            f"{cam['errors']} | {cam['achieved_fps']:.1f} | "
            f"{_target_label(cam['target_fps'])} | {_hit_label(cam['hit_target'])} | "
            f"{cam['latency_p50_sec']:.3f} | {cam['latency_p95_sec']:.3f} |"
        )
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Combined cross-run plots
# ---------------------------------------------------------------------------


def _write_combined_plots(
    out_root: Path,
    summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build plots/system_utilization.png and plots/fps_{lens}_camera_{N}.png
    spanning all runs on a benchmark-wall-clock axis. Returns relative paths
    to the generated plots for embedding in summary.md."""
    plots_dir = out_root / "plots"
    plots_dir.mkdir(exist_ok=True)
    benchmark_t0 = min(s["meta"]["main_start_ts"] for s in summaries)

    # Parse every run's log into combined series.
    cpu_pct: dict[float, float] = {}
    gpu_pct: dict[float, float] = {}
    ram_gb: dict[float, float] = {}
    vram_gb: dict[float, float] = {}
    ram_total = vram_total = 0.0
    by_camera_frames: dict[tuple[str, int], dict[int, int]] = defaultdict(
        lambda: defaultdict(int))
    by_camera_errors: dict[tuple[str, int], dict[int, int]] = defaultdict(
        lambda: defaultdict(int))

    for s in summaries:
        meta = s["meta"]
        run_t0 = meta["main_start_ts"]
        run_end = meta["main_end_ts"]
        run_dir = out_root / f"run_{int(meta['run_index']):02d}"
        log_file = run_dir / "load_test.log"
        if not log_file.exists():
            continue
        with log_file.open() as f:
            for line in f:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                payload = json.loads(line)
                ts = float(payload.get("ts", 0))
                if ts < run_t0 or ts >= run_end:
                    continue
                offset = ts - benchmark_t0
                event = payload.get("event")
                if event == "cpu":
                    cpu_pct[offset] = float(payload.get("cpu_percent", 0))
                    ram_gb[offset] = float(payload.get("ram_used_gb", 0))
                    ram_total = max(ram_total, float(payload.get("ram_total_gb", 0)))
                elif event == "gpu":
                    gpu_pct[offset] = float(payload.get("gpu_utilization", 0))
                    vram_gb[offset] = float(payload.get("vram_used_gb", 0))
                    vram_total = max(vram_total, float(payload.get("vram_total_gb", 0)))
                elif event == "request":
                    key = (payload.get("lens_name", "_"), int(payload.get("camera", 0)))
                    if _is_frame(payload):
                        by_camera_frames[key][int(offset)] += 1
                    if not payload.get("success", True):
                        by_camera_errors[key][int(offset)] += 1

    boundaries = [
        (s["meta"]["main_start_ts"] - benchmark_t0,
         int(s["meta"]["run_index"]),
         s["meta"].get("lens_n", {}))
        for s in summaries
    ]
    target_by_lens: dict[str, float] = {}
    for s in summaries:
        for l in s["meta"].get("lenses", []):
            target_by_lens[l["name"]] = l["target_fps"]

    refs: dict[str, Any] = {}

    sys_path = plots_dir / "system_utilization.png"
    if _plot_combined_system(
        sys_path, cpu_pct, gpu_pct, ram_gb, ram_total, vram_gb, vram_total, boundaries,
    ):
        refs["system"] = f"plots/{sys_path.name}"

    fps_refs: list[tuple[tuple[str, int], str]] = []
    for (lens, camera), buckets in sorted(by_camera_frames.items()):
        fps_path = plots_dir / f"fps_{lens}_camera_{camera}.png"
        if _plot_combined_camera_fps(
            fps_path, lens, camera, buckets,
            by_camera_errors.get((lens, camera), {}),
            target_by_lens.get(lens), boundaries,
        ):
            fps_refs.append(((lens, camera), f"plots/{fps_path.name}"))
    refs["fps_per_camera"] = fps_refs
    return refs


def _draw_boundary_lines(
    ax,
    boundaries: list[tuple[float, int, dict[str, int]]],
) -> None:
    """Just the vertical lines, no labels. Use when the same axis shares an
    x-axis with another that carries the labels."""
    for offset, _run_idx, _lens_n in boundaries:
        ax.axvline(offset, color="gray", linestyle=":", alpha=0.6, linewidth=1.0)


def _annotate_boundaries(
    ax,
    boundaries: list[tuple[float, int, dict[str, int]]],
    lens_name: str | None = None,
) -> None:
    """Draw a vertical line at each boundary AND a label below the x-axis,
    rotated 30° so labels stack neatly without overlapping chart content."""
    for offset, run_idx, lens_n in boundaries:
        ax.axvline(offset, color="gray", linestyle=":", alpha=0.6, linewidth=1.0)
        if lens_name is not None and lens_name in lens_n:
            label = f"Run {run_idx} (n={lens_n[lens_name]})"
        else:
            label = f"Run {run_idx}"
        # xy=(offset, 0) in (data, axes) coords; xytext nudges below the axis.
        ax.annotate(
            label, xy=(offset, 0), xycoords=("data", "axes fraction"),
            xytext=(2, -16), textcoords="offset points",
            fontsize=8, color="dimgray",
            rotation=30, ha="right", va="top", rotation_mode="anchor",
            annotation_clip=False,
        )


def _plot_combined_system(
    path: Path,
    cpu_pct, gpu_pct, ram_gb, ram_total, vram_gb, vram_total,
    boundaries,
) -> bool:
    if not any((cpu_pct, gpu_pct, ram_gb, vram_gb)):
        return False
    fig, axes = plt.subplots(2, 2, figsize=(13, 8.5), sharex=True)
    cpu_ax, gpu_ax = axes[0]
    ram_ax, vram_ax = axes[1]
    _plot_pct(cpu_ax, cpu_pct, "CPU utilization", color="tab:blue")
    _plot_pct(gpu_ax, gpu_pct, "GPU compute utilization", color="tab:red")
    _plot_gb(ram_ax, ram_gb, ram_total, "RAM used", color="tab:green")
    _plot_gb(vram_ax, vram_gb, vram_total, "VRAM used", color="tab:purple")
    # Vertical lines on every panel; labels only on the bottom row (x-axis
    # is shared, so labels on the top row would be hidden anyway).
    for ax in (cpu_ax, gpu_ax):
        _draw_boundary_lines(ax, boundaries)
        ax.grid(True, alpha=0.3)
    for ax in (ram_ax, vram_ax):
        _annotate_boundaries(ax, boundaries)
        ax.set_xlabel("seconds since benchmark start")
        ax.grid(True, alpha=0.3)
    fig.suptitle("System utilization (all runs)", fontsize=14)
    fig.tight_layout()
    # Leave room for the rotated run-boundary labels below the bottom row.
    fig.subplots_adjust(bottom=0.15)
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return True


def _plot_combined_camera_fps(
    path: Path,
    lens_name: str,
    camera: int,
    frame_buckets: dict[int, int],
    error_buckets: dict[int, int],
    target_fps: float | None,
    boundaries,
) -> bool:
    if not frame_buckets:
        return False
    seconds = sorted(frame_buckets.keys())
    fps_values = [frame_buckets[s] for s in seconds]
    fig, ax = plt.subplots(figsize=(13, 4.5))
    line_fps, = ax.plot(seconds, fps_values, color="tab:blue",
                        marker="o", markersize=2.5, linewidth=1.1, label="FPS")
    handles: list = [line_fps]
    if target_fps is not None and target_fps > 0:
        line_target = ax.axhline(target_fps, color="tab:orange", linestyle="--", alpha=0.8,
                                 label=f"target {target_fps:.1f} fps")
        handles.append(line_target)
    ax.set_title(f"{lens_name} — camera {camera} — FPS (all runs)")
    ax.set_xlabel("seconds since benchmark start")
    ax.set_ylabel("frames per second", color="tab:blue")
    ax.tick_params(axis="y", labelcolor="tab:blue")
    ax.set_ylim(bottom=0)
    ax.grid(True, alpha=0.3)

    ax_err = ax.twinx()
    err_seconds = sorted(set(seconds) | set(error_buckets.keys()))
    err_values = [error_buckets.get(s, 0) for s in err_seconds]
    line_err, = ax_err.plot(err_seconds, err_values, color="tab:red",
                            linewidth=1.2, label="failed requests / sec")
    ax_err.set_ylabel("failed requests / sec", color="tab:red")
    ax_err.tick_params(axis="y", labelcolor="tab:red")
    ax_err.set_ylim(bottom=0)
    handles.append(line_err)

    _annotate_boundaries(ax, boundaries, lens_name=lens_name)
    ax.legend(handles=handles, loc="lower right")
    fig.tight_layout()
    fig.subplots_adjust(bottom=0.20)
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return True
