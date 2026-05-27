"""Per-run + cross-run summaries and plots from the JSONL request log.

Output layout under each benchmark's output_dir:

    summary.md          ← single consolidated doc (overview + per-run sections)
    summary.json        ← cross-run machine-readable
    plots/
        system_utilization.png    ← 2x2 grid: CPU%, GPU%, RAM GB, VRAM GB
        fps_all_lenses.png        ← mosaic of every lens's overlay plot
        fps_{lens}.png            ← per-lens overlay (cameras as colored lines)
        fps_{lens}_camera_{N}.png ← per-(lens, camera) detail (on disk only)
    run_NN/
        load_test.log
        summary.json    ← per-run machine-readable
        plots/
            fps_{lens}_camera_{N}.png
            system_utilization.png

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


def _camera_logs(run_dir: Path) -> list[Path]:
    """Per-camera worker logs in a run directory (`camera_*.log`)."""
    return sorted(run_dir.glob("camera_*.log"))


def _read_request_events(run_dir: Path, start_ts: float, end_ts: float) -> list[dict]:
    """Read every `event: request` line whose `ts` falls in [start, end)
    across every per-camera log in `run_dir`.

    Args:
        run_dir: Per-run directory (e.g. `out_root/run_00/`).
        start_ts: Inclusive lower bound (== main_start_ts).
        end_ts: Exclusive upper bound (== main_end_ts).

    Returns:
        Flat list of request-event dicts from all camera logs.
    """
    out: list[dict] = []
    for log_file in _camera_logs(run_dir):
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


def _read_resource_events(run_dir: Path, start_ts: float, end_ts: float) -> dict[str, Any]:
    """Read cpu/gpu events from `run_dir/system.log` and bucket by
    seconds-since-start.

    Args:
        run_dir: Per-run directory (contains `system.log` written by
            SystemMonitor).
        start_ts: Inclusive lower bound (== main_start_ts).
        end_ts: Exclusive upper bound (== main_end_ts).

    Returns:
        Dictionary with keys:
            - "cpu_pct": {seconds_offset: cpu_percent} float series
            - "gpu_pct": {seconds_offset: gpu_compute_percent} float series
            - "ram_gb": {seconds_offset: ram_used_gb} float series
            - "ram_total_gb": float — max RAM total seen (for the y-axis reference line)
            - "vram_gb": {seconds_offset: vram_used_gb} float series
            - "vram_total_gb": float — max VRAM total seen
    """
    cpu_pct: dict[float, float] = {}
    ram_gb: dict[float, float] = {}
    gpu_pct: dict[float, float] = {}
    vram_gb: dict[float, float] = {}
    ram_total = 0.0
    vram_total = 0.0
    system_log = run_dir / "system.log"
    if not system_log.exists():
        return {
            "cpu_pct": cpu_pct, "gpu_pct": gpu_pct,
            "ram_gb": ram_gb, "ram_total_gb": ram_total,
            "vram_gb": vram_gb, "vram_total_gb": vram_total,
        }
    with system_log.open() as f:
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
    """True if `event` represents one lens-loop iteration.

    For single-stage lenses every request is a frame (no `stage` field).
    For `bbox_to_binary`, each frame produces 1 bbox request + N binary
    requests; only the upstream `bbox` event counts as a frame here.

    Per-event check (rather than "any event has stage") so the predicate
    works correctly on a mixed-lens event stream — e.g. computing the
    aggregate frame count across all lenses in a run.
    """
    return "stage" not in event or event.get("stage") == "bbox"


def _summarize(events: list[dict], target_fps: float | None, duration_s: float) -> dict[str, Any]:
    """Compute per-camera (or per-run aggregate) stats over a fixed window.

    FPS is computed as `total_frames / duration_s` — the intended window
    length, not `max(ts) - min(ts)`. This keeps a late-tail request from
    inflating duration and quietly under-reporting FPS.

    Args:
        events: All request events in scope (within the measurement
            window; could be one camera's events, or every camera's
            events for the aggregate).
        target_fps: Per-camera FPS target, or None when no target
            applies (used to compute the Hit verdict).
        duration_s: Fixed window length (main_end_ts - main_start_ts).

    Returns:
        Dict with keys:
            - "total_frames": int — count of lens-loop iterations
            - "total_requests": int — count of HTTP requests (≥ frames for chained)
            - "errors": int — count of `success: False` events
            - "duration_seconds": float — echoed back for clarity
            - "achieved_fps": float — total_frames / duration_s
            - "target_fps": float | None — echoed back
            - "hit_target": bool | None — achieved_fps >= 0.95 * target_fps,
              None when target_fps is 0 or None (saturate / no target)
            - "latency_p50_sec": float — interpolated p50 of request latency
            - "latency_p95_sec": float — interpolated p95 of request latency
    """
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
    run_meta: dict[str, Any],
    *,
    main_start_ts: float,
    main_end_ts: float,
) -> dict[str, Any]:
    """Build all per-run artifacts: stats, plots, and summary.json.

    Reads per-camera logs (`camera_*.log`) and the system monitor log
    (`system.log`) directly from `run_dir`. Cross-references
    `run_meta["lenses"]` against observed events so cameras that produced
    no events get a flagged row rather than silently disappearing.

    Args:
        run_dir: Per-run output dir (`out_root/run_NN/`). Created by the
            caller before this is called. Contains one `camera_*.log`
            per worker plus `system.log`.
        run_meta: Metadata produced by cli._run_one; carries lens config,
            durations, main_start_ts, main_end_ts, and worker_failures.
        main_start_ts: Inclusive start of the measurement window.
        main_end_ts: Exclusive end of the measurement window.

    Returns:
        Per-run summary dict (also written to run_dir/summary.json),
        used by write_top_level to assemble the consolidated doc.
    """
    duration_s = main_end_ts - main_start_ts
    events = _read_request_events(run_dir, start_ts=main_start_ts, end_ts=main_end_ts)
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
    _plot_run(run_dir, by_camera, target_by_lens, main_start_ts, main_end_ts)
    return summary


def _plot_run(
    run_dir: Path,
    by_camera: dict[tuple[str, int], list[dict]],
    target_by_lens: dict[str, float],
    main_start_ts: float,
    main_end_ts: float,
) -> None:
    plots_dir = run_dir / "plots"
    plots_dir.mkdir(exist_ok=True)
    for (lens_name, camera), events in sorted(by_camera.items()):
        _plot_camera_fps(plots_dir, lens_name, camera, events,
                         target_by_lens.get(lens_name), main_start_ts)
    _plot_system_grid(plots_dir, run_dir, main_start_ts, main_end_ts)


def _plot_camera_fps(
    plots_dir: Path,
    lens_name: str,
    camera: int,
    events: list[dict],
    target_fps: float | None,
    main_start_ts: float,
) -> None:
    """Write the per-run FPS plot for one (lens, camera).

    The plot has two y-axes:
      - Left (blue): frames/sec, dotted markers per second, with an
        orange dashed reference line at target_fps when set.
      - Right (red): failed requests / sec.

    Args:
        plots_dir: Where to write `fps_{lens_name}_camera_{camera}.png`.
        lens_name: Used in the title and filename.
        camera: Used in the title and filename.
        events: Request events for THIS camera within the measurement
            window.
        target_fps: Per-lens target; None or 0 skips the target line.
        main_start_ts: Used to compute seconds-since-main-start for the
            x-axis (matches the FPS plot's bucketing).
    """
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


def _plot_system_grid(plots_dir: Path, run_dir: Path, main_start_ts: float, main_end_ts: float) -> None:
    """Write the per-run 2×2 system utilization grid (CPU %, GPU %,
    RAM GB, VRAM GB) from `run_dir/system.log`. No-op when the log has
    no cpu/gpu events (e.g. /status/resources.json was unreachable)."""
    parsed = _read_resource_events(run_dir, main_start_ts, main_end_ts)
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


def summarize_lenses_config(cfg, stage_detectors) -> list[dict[str, Any]]:
    """Build the per-lens configuration summary surfaced in summary.md /
    summary.json.

    Combines the YAML config (per-lens shape and pipelines) with the
    resolved StageDetector list (which carries the actual detector_id
    and the is_external flag from Feature 1). The result is the
    authoritative "what actually ran" record — it makes pipeline-vs-ID
    mismatches obvious when reviewing past benchmarks and lets
    downstream tooling diff configurations across runs.

    Args:
        cfg: BenchmarkConfig (passed positionally to avoid a circular
            import; we only read public attributes).
        stage_detectors: Flat list of StageDetector with lens_name,
            stage, detector_id, is_external.

    Returns:
        A list of dicts, one per lens, in config order. Each entry:
            {
              "name": str,
              "type": "single_binary" | "single_bbox" | "bbox_to_binary",
              "cameras": int,
              "n": list[int] | None,
              "image_size": [w, h] | None,           # only if overridden
              "target_fps": float | None,            # only if overridden
              "stages": [
                {
                  "stage": "single" | "bbox" | "binary",
                  "pipeline": str | None,
                  "detector_id": str,
                  "is_external": bool,
                },
                ...
              ],
            }
    """
    stages_by_lens: dict[str, list] = defaultdict(list)
    for sd in stage_detectors:
        stages_by_lens[sd.lens_name].append(sd)

    out: list[dict[str, Any]] = []
    for lens in cfg.lenses:
        sds = stages_by_lens.get(lens.name, [])
        sd_by_stage = {sd.stage: sd for sd in sds}
        ltype = getattr(lens, "type", "?")

        stage_entries: list[dict[str, Any]] = []
        if ltype in ("single_binary", "single_bbox"):
            sd = sd_by_stage.get("single")
            stage_entries.append({
                "stage": "single",
                "pipeline": getattr(lens, "pipeline", None),
                "detector_id": sd.detector_id if sd else None,
                "is_external": sd.is_external if sd else False,
            })
        elif ltype == "bbox_to_binary":
            sd_bbox = sd_by_stage.get("bbox")
            sd_bin = sd_by_stage.get("binary")
            stage_entries.append({
                "stage": "bbox",
                "pipeline": getattr(lens, "bbox_pipeline", None),
                "detector_id": sd_bbox.detector_id if sd_bbox else None,
                "is_external": sd_bbox.is_external if sd_bbox else False,
            })
            stage_entries.append({
                "stage": "binary",
                "pipeline": getattr(lens, "binary_pipeline", None),
                "detector_id": sd_bin.detector_id if sd_bin else None,
                "is_external": sd_bin.is_external if sd_bin else False,
            })

        entry: dict[str, Any] = {
            "name": lens.name,
            "type": ltype,
            "cameras": lens.cameras,
            "n": list(lens.n) if hasattr(lens, "n") else None,
            "stages": stage_entries,
        }
        if lens.image_size is not None:
            entry["image_size"] = list(lens.image_size)
        if lens.target_fps is not None:
            entry["target_fps"] = lens.target_fps
        out.append(entry)
    return out


def _render_lens_config_section(lenses: list[dict[str, Any]]) -> list[str]:
    """Render the lens-configuration table for summary.md.

    One row per stage (chained lenses produce two rows). The detector_id
    column shows the resolved detector along with an `(external)` tag
    for stages backed by a pre-existing detector — those are the ones
    whose pipeline was verified at startup, not created or trained by
    the benchmark.
    """
    if not lenses:
        return []
    lines = [
        "## Lens configuration",
        "",
        "Resolved configuration for each lens — pipeline and detector ID "
        "as actually used at runtime. Stages tagged `(external)` were "
        "supplied via `*_detector_id` in the YAML; their pipeline was "
        "verified to match the config before the benchmark ran, and they "
        "are preserved at cleanup.",
        "",
        "| Lens | Type | Stage | Pipeline | Detector ID | Cameras | n |",
        "|---|---|---|---|---|---:|---|",
    ]
    for lens in lenses:
        n_label = ",".join(str(v) for v in lens["n"]) if lens.get("n") else "—"
        cams = lens["cameras"]
        cams_label = ",".join(str(v) for v in cams) if isinstance(cams, list) else str(cams)
        for i, stage in enumerate(lens["stages"]):
            pipeline = stage.get("pipeline") or "(default)"
            det_id = stage.get("detector_id") or "—"
            if stage.get("is_external"):
                det_id = f"{det_id} (external)"
            # Repeat the lens-level columns only on the first stage row so
            # chained lenses read as a single logical entry.
            if i == 0:
                lines.append(
                    f"| {lens['name']} | {lens['type']} | {stage['stage']} | "
                    f"`{pipeline}` | `{det_id}` | {cams_label} | {n_label} |"
                )
            else:
                lines.append(
                    f"|  |  | {stage['stage']} | `{pipeline}` | `{det_id}` |  |  |"
                )
    lines.append("")
    return lines


def write_top_level(
    out_root: Path,
    summaries: list[dict[str, Any]],
    *,
    benchmark_meta: dict[str, Any],
    network_baseline: dict | None,
    network_baseline_text: str,
) -> None:
    """Write the consolidated top-level summary.md, summary.json, and
    cross-run combined plots.

    summary.md sections:
        1. Environment header (name, started_at, edge URL, ping baseline, defaults)
        2. Overview table (one row per run, per-lens mean FPS + Hit verdict)
        3. Combined system_utilization.png embedded
        4. One combined FPS plot per (lens, camera) embedded
        5. Per-run sections with full per-camera tables

    Args:
        out_root: Top-level benchmark output directory.
        summaries: Output of every `write_run_artifacts` call, in run order.
        benchmark_meta: Top-level metadata produced by cli.main (name,
            started_at, edge_endpoint_url, config defaults).
        network_baseline: Result of network.measure (or None).
        network_baseline_text: Pre-formatted version of the above for
            inline rendering.
    """
    # `lenses` is the structured mirror of the Lens configuration section
    # below; it captures the resolved (post-validation, post-detector-fetch)
    # state of every lens so downstream tools can diff configs across runs.
    lenses_config = benchmark_meta.get("lenses", [])
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

    lines.extend(_render_lens_config_section(lenses_config))

    if not summaries:
        lines.append("(no runs)")
        (out_root / "summary.md").write_text("\n".join(lines) + "\n")
        return

    lines.append("## Overview")
    lines.append("")
    lens_names = sorted({c["lens_name"] for s in summaries for c in s.get("cameras", [])})
    per_lens_cols = [c for lens in lens_names for c in (f"{lens} FPS", f"{lens} Hit")]
    # Surface the per-run camera count only when there's a cameras ramp
    # anywhere in the config — otherwise the column would be constant
    # noise. Detected by checking if any lens has a list-typed `cameras`
    # in the Lens configuration block.
    cameras_ramped = any(
        isinstance(l.get("cameras"), list) for l in lenses_config
    )
    lines.append(
        f"Per-lens FPS = mean across that lens's camera processes. "
        f"Hit = `yes` if every camera hit ≥{int(_FPS_HIT_TOLERANCE * 100)}% of its target."
        + (" `lens_cameras` shows the per-run camera count per lens." if cameras_ramped else "")
    )
    lines.append("")
    header = ["run", "lens_n"]
    if cameras_ramped:
        header.append("lens_cameras")
    header += per_lens_cols
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")
    for s in summaries:
        meta = s["meta"]
        cells = [str(meta.get("run_index", "?")), f"`{meta.get('lens_n', {})}`"]
        if cameras_ramped:
            cells.append(f"`{meta.get('lens_cameras', {})}`")
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

    if plot_refs.get("fps_mosaic") or plot_refs.get("fps_per_lens"):
        lines.append("## Cross-run FPS")
        lines.append("")
        if plot_refs.get("fps_mosaic"):
            lines.append(
                "Overview of every lens at a glance. Each cell shows that "
                "lens's FPS with one colored line per camera (viridis, "
                "blue→yellow with camera index). Cameras that only existed "
                "in later runs start partway through the time axis. "
                "Aggregate failed-requests rate is overlaid in red on a "
                "secondary axis."
            )
            lines.append("")
            lines.append(f"![FPS overview]({plot_refs['fps_mosaic']})")
            lines.append("")
        if plot_refs.get("fps_per_lens"):
            lines.append("### Per-lens detail")
            lines.append("")
            for lens, rel_path in plot_refs["fps_per_lens"]:
                lines.append(f"#### {lens}")
                lines.append("")
                lines.append(f"![{lens} fps]({rel_path})")
                lines.append("")
        if plot_refs.get("fps_per_camera"):
            lines.append(
                f"_Per-(lens, camera) detail PNGs live under "
                f"`plots/fps_{{lens}}_camera_{{N}}.png` for ad-hoc "
                f"inspection — {len(plot_refs['fps_per_camera'])} file(s)._"
            )
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
    lines.append("| Lens | Camera | Frames | Errors | FPS | Target | Hit | p50 (s) | p95 (s) | Note |")
    lines.append("|---|---:|---:|---:|---:|---:|:---:|---:|---:|---|")
    for cam in s.get("cameras", []):
        if cam.get("no_events"):
            lines.append(
                f"| {cam['lens_name']} | {cam['camera']} | 0 | ? | 0.0 | "
                f"{_target_label(cam['target_fps'])} | {_hit_label(cam['hit_target'])} | "
                f"— | — | ⚠ no events captured (worker likely crashed) |"
            )
            continue
        lines.append(
            f"| {cam['lens_name']} | {cam['camera']} | {cam['total_frames']} | "
            f"{cam['errors']} | {cam['achieved_fps']:.1f} | "
            f"{_target_label(cam['target_fps'])} | {_hit_label(cam['hit_target'])} | "
            f"{cam['latency_p50_sec']:.3f} | {cam['latency_p95_sec']:.3f} |  |"
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
    """Build cross-run combined plots and return their relative paths.

    Reads every run's load_test.log, re-bases events on the benchmark
    wall-clock (`offset = ts - first_run.main_start_ts`), and writes:
      - plots/system_utilization.png  — 2x2 CPU%, GPU%, RAM GB, VRAM GB
      - plots/fps_all_lenses.png      — mosaic of per-lens FPS overlays
      - plots/fps_{lens}.png          — one per lens, cameras overlaid
      - plots/fps_{lens}_camera_{N}.png — per (lens, camera) detail files
        (kept on disk for ad-hoc inspection, not embedded in summary.md)

    Each plot has dotted vertical lines at every run's main_start with
    labels below the x-axis (system plot: "Run i"; FPS plots:
    "Run i (n=X)" using that lens's own n, plus ", cams=Y" when the
    camera count varies across runs).

    Args:
        out_root: Top-level benchmark output dir.
        summaries: All per-run summaries (each contains main_start_ts /
            main_end_ts that bound the event window for that run).

    Returns:
        Dict with keys:
            - "system": "plots/system_utilization.png" or absent
            - "fps_mosaic": "plots/fps_all_lenses.png" or absent
            - "fps_per_lens": list of (lens, relative_path) — one per lens
            - "fps_per_camera": list of ((lens, camera), relative_path)
              (files exist on disk but not embedded in summary.md)
    """
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
        # Resource events live in system.log; request events live in
        # per-camera camera_*.log files.
        for log_file in _camera_logs(run_dir):
            with log_file.open() as f:
                for line in f:
                    line = line.strip()
                    if not line.startswith("{"):
                        continue
                    payload = json.loads(line)
                    if payload.get("event") != "request":
                        continue
                    ts = float(payload.get("ts", 0))
                    if ts < run_t0 or ts >= run_end:
                        continue
                    offset = ts - benchmark_t0
                    key = (payload.get("lens_name", "_"), int(payload.get("camera", 0)))
                    if _is_frame(payload):
                        by_camera_frames[key][int(offset)] += 1
                    if not payload.get("success", True):
                        by_camera_errors[key][int(offset)] += 1
        system_log = run_dir / "system.log"
        if system_log.exists():
            with system_log.open() as f:
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

    boundaries = [
        (s["meta"]["main_start_ts"] - benchmark_t0,
         int(s["meta"]["run_index"]),
         s["meta"].get("lens_n", {}),
         s["meta"].get("lens_cameras", {}))
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

    # Per-(lens, camera) detail plots — files only, not embedded.
    fps_per_camera_refs: list[tuple[tuple[str, int], str]] = []
    for (lens, camera), buckets in sorted(by_camera_frames.items()):
        fps_path = plots_dir / f"fps_{lens}_camera_{camera}.png"
        if _plot_combined_camera_fps(
            fps_path, lens, camera, buckets,
            by_camera_errors.get((lens, camera), {}),
            target_by_lens.get(lens), boundaries,
        ):
            fps_per_camera_refs.append(((lens, camera), f"plots/{fps_path.name}"))
    refs["fps_per_camera"] = fps_per_camera_refs

    # Regroup per-camera buckets into per-lens shape so the overlay
    # plots can render each lens's cameras as colored lines on one axis.
    frames_by_lens: dict[str, dict[int, dict[int, int]]] = defaultdict(dict)
    errors_by_lens: dict[str, dict[int, dict[int, int]]] = defaultdict(dict)
    for (lens, camera), buckets in by_camera_frames.items():
        frames_by_lens[lens][camera] = buckets
    for (lens, camera), buckets in by_camera_errors.items():
        errors_by_lens[lens][camera] = buckets

    # Per-lens overlay plots (one PNG per lens, cameras as colored lines).
    fps_per_lens_refs: list[tuple[str, str]] = []
    lenses_data: list[tuple[str, dict[int, dict[int, int]],
                            dict[int, dict[int, int]], float | None]] = []
    for lens in sorted(frames_by_lens.keys()):
        cam_frames = frames_by_lens[lens]
        cam_errors = errors_by_lens.get(lens, {})
        target = target_by_lens.get(lens)
        lens_path = plots_dir / f"fps_{lens}.png"
        if _plot_combined_lens_fps(lens_path, lens, cam_frames, cam_errors, target, boundaries):
            fps_per_lens_refs.append((lens, f"plots/{lens_path.name}"))
        lenses_data.append((lens, cam_frames, cam_errors, target))
    refs["fps_per_lens"] = fps_per_lens_refs

    # Mosaic — single image showing every lens's overlay plot at once.
    mosaic_path = plots_dir / "fps_all_lenses.png"
    if _plot_all_lenses_mosaic(mosaic_path, lenses_data, boundaries):
        refs["fps_mosaic"] = f"plots/{mosaic_path.name}"

    return refs


def _draw_boundary_lines(
    ax,
    boundaries: list[tuple[float, int, dict[str, int], dict[str, int]]],
) -> None:
    """Draw a dotted vertical line on `ax` at each run boundary, no labels.

    Used on the top row of the 2x2 system grid where the x-axis is
    shared with the bottom row — labels would be hidden, so we just
    draw the lines for visual continuity across panels.

    Args:
        ax: Matplotlib axis to draw on.
        boundaries: List of (x_offset_seconds, run_index, lens_n_dict,
            lens_cameras_dict). Only the first element matters here.
    """
    for offset, *_ in boundaries:
        ax.axvline(offset, color="gray", linestyle=":", alpha=0.6, linewidth=1.0)


def _annotate_boundaries(
    ax,
    boundaries: list[tuple[float, int, dict[str, int], dict[str, int]]],
    lens_name: str | None = None,
) -> None:
    """Draw vertical lines at run boundaries AND rotated labels below the axis.

    Labels live below the x-axis (rotated 30°) so they don't overlap
    chart content. Callers must pair this with
    `fig.subplots_adjust(bottom=...)` to reserve the space.

    Args:
        ax: Matplotlib axis to annotate.
        boundaries: List of (x_offset_seconds, run_index, lens_n_dict,
            lens_cameras_dict) for each run.
        lens_name: When set, labels look like "Run i (n=X)" using
            `lens_n_dict[lens_name]`, and additionally include
            `, cams=Y` from `lens_cameras_dict[lens_name]` when the
            camera count varies across runs (a cameras-ramp). When
            None, labels are just "Run i" (used on the global system
            util plot since different lenses can have different sweep
            values).
    """
    # Detect once whether any lens has a varying camera count — drives
    # whether we annotate cameras on each label.
    cameras_ramped = (
        lens_name is not None
        and len({b[3].get(lens_name) for b in boundaries if b[3]}) > 1
    )
    for offset, run_idx, lens_n, lens_cameras in boundaries:
        ax.axvline(offset, color="gray", linestyle=":", alpha=0.6, linewidth=1.0)
        parts: list[str] = []
        if lens_name is not None and lens_name in lens_n:
            parts.append(f"n={lens_n[lens_name]}")
        if cameras_ramped and lens_name in lens_cameras:
            parts.append(f"cams={lens_cameras[lens_name]}")
        label = f"Run {run_idx}"
        if parts:
            label += f" ({', '.join(parts)})"
        # xy=(offset, 0) in (data, axes) coords; xytext nudges well below the
        # x-axis label so the rotated text doesn't collide with "seconds since
        # benchmark start". Pair with subplots_adjust(bottom=...) at the caller.
        ax.annotate(
            label, xy=(offset, 0), xycoords=("data", "axes fraction"),
            xytext=(2, -38), textcoords="offset points",
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
    # Reserve space below the bottom-row xlabels for the rotated
    # "Run i" labels — without this they collide with "seconds since
    # benchmark start".
    fig.subplots_adjust(bottom=0.18)
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
    # Reserve space below the xlabel for the rotated "Run i (n=X)" labels.
    fig.subplots_adjust(bottom=0.28)
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return True


def _draw_lens_fps_on_axis(
    ax,
    lens_name: str,
    cameras_frame_buckets: dict[int, dict[int, int]],
    cameras_error_buckets: dict[int, dict[int, int]],
    target_fps: float | None,
    boundaries,
    *,
    annotate_runs: bool = True,
    show_legend: bool = True,
) -> bool:
    """Draw a lens's FPS overlay on the given axis.

    One colored line per camera (viridis colormap, blue → yellow with
    increasing camera index). Cameras that only existed in later runs
    naturally start partway through the time axis. Errors from all
    cameras of the lens are summed and drawn as a single red line on a
    twin y-axis (per-camera error curves would be too crowded in the
    overlay).

    Args:
        ax: Matplotlib axis to draw on.
        lens_name: Lens identifier (used in title + boundary labels).
        cameras_frame_buckets: Mapping camera_idx -> {second: frame_count}.
        cameras_error_buckets: Mapping camera_idx -> {second: error_count}.
        target_fps: Optional target FPS line.
        boundaries: Run-boundary tuples (see _annotate_boundaries).
        annotate_runs: Whether to draw the rotated "Run i (n=X)" labels
            below the axis. Disable in mosaic subplots where label space
            is tight.
        show_legend: Whether to draw the camera legend. Disable in
            mosaic subplots if the figure-level legend covers it.

    Returns:
        True if any frame data was plotted, False if the lens had no
        events at all (caller should treat as no-data).
    """
    if not cameras_frame_buckets:
        return False
    camera_indices = sorted(cameras_frame_buckets.keys())
    cmap = plt.get_cmap("viridis")
    handles: list = []
    for i, cam in enumerate(camera_indices):
        buckets = cameras_frame_buckets[cam]
        if not buckets:
            continue
        seconds = sorted(buckets.keys())
        fps_values = [buckets[s] for s in seconds]
        # Edge case: single camera → use the colormap's mid value so the
        # line is visible against the default theme rather than nearly
        # white at the top of viridis.
        color_pos = i / (len(camera_indices) - 1) if len(camera_indices) > 1 else 0.4
        line, = ax.plot(seconds, fps_values, color=cmap(color_pos),
                        marker="o", markersize=2.0, linewidth=1.1,
                        label=f"cam {cam}")
        handles.append(line)
    if target_fps is not None and target_fps > 0:
        line_target = ax.axhline(target_fps, color="tab:orange", linestyle="--", alpha=0.8,
                                 label=f"target {target_fps:.1f} fps")
        handles.append(line_target)
    ax.set_title(f"{lens_name} — FPS per camera (all runs)")
    ax.set_xlabel("seconds since benchmark start")
    ax.set_ylabel("frames per second")
    ax.set_ylim(bottom=0)
    ax.grid(True, alpha=0.3)

    # Aggregate errors across every camera for this lens — a single red
    # line on a twin y-axis keeps the overlay readable.
    all_err_seconds: set[int] = set()
    for buckets in cameras_error_buckets.values():
        all_err_seconds.update(buckets.keys())
    if all_err_seconds:
        ax_err = ax.twinx()
        err_seconds = sorted(all_err_seconds)
        err_values = [
            sum(cameras_error_buckets[cam].get(s, 0)
                for cam in cameras_error_buckets)
            for s in err_seconds
        ]
        line_err, = ax_err.plot(err_seconds, err_values, color="tab:red",
                                linewidth=1.2, label="failed requests / sec (sum)")
        ax_err.set_ylabel("failed requests / sec (sum)", color="tab:red")
        ax_err.tick_params(axis="y", labelcolor="tab:red")
        ax_err.set_ylim(bottom=0)
        handles.append(line_err)

    if annotate_runs:
        _annotate_boundaries(ax, boundaries, lens_name=lens_name)
    else:
        _draw_boundary_lines(ax, boundaries)
    if show_legend:
        ax.legend(handles=handles, loc="lower right", fontsize=8)
    return True


def _plot_combined_lens_fps(
    path: Path,
    lens_name: str,
    cameras_frame_buckets: dict[int, dict[int, int]],
    cameras_error_buckets: dict[int, dict[int, int]],
    target_fps: float | None,
    boundaries,
) -> bool:
    """Single-axis lens overlay plot. Returns False if no frames were
    captured for any camera of the lens (no file written)."""
    fig, ax = plt.subplots(figsize=(13, 4.5))
    had_data = _draw_lens_fps_on_axis(
        ax, lens_name, cameras_frame_buckets, cameras_error_buckets,
        target_fps, boundaries, annotate_runs=True, show_legend=True,
    )
    if not had_data:
        plt.close(fig)
        return False
    fig.tight_layout()
    fig.subplots_adjust(bottom=0.28)
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return True


def _plot_all_lenses_mosaic(
    path: Path,
    lenses_data: list[tuple[str, dict[int, dict[int, int]],
                            dict[int, dict[int, int]], float | None]],
    boundaries,
) -> bool:
    """2-column mosaic of per-lens FPS overlay plots.

    `lenses_data` is a list of (lens_name, cameras_frame_buckets,
    cameras_error_buckets, target_fps) — one entry per lens.

    Layout: 2 columns × ceil(N/2) rows. Unused cells (when N is odd)
    are hidden. Each subplot gets its own legend; the mosaic is meant
    to be the "see everything at once" view at the top of the
    Cross-run FPS section.
    """
    if not lenses_data:
        return False
    n_lenses = len(lenses_data)
    ncols = 2 if n_lenses > 1 else 1
    nrows = (n_lenses + ncols - 1) // ncols
    fig, axes = plt.subplots(
        nrows, ncols,
        figsize=(13 * ncols / 2, 4.0 * nrows),
        squeeze=False,
    )
    flat_axes = axes.flatten()
    any_drawn = False
    for i, (lens_name, frame_buckets, error_buckets, target_fps) in enumerate(lenses_data):
        ax = flat_axes[i]
        drawn = _draw_lens_fps_on_axis(
            ax, lens_name, frame_buckets, error_buckets, target_fps, boundaries,
            # Mosaic cells are tight — skip the rotated boundary labels
            # (lines only) and use a compact legend.
            annotate_runs=False, show_legend=True,
        )
        if drawn:
            any_drawn = True
    # Hide any unused cells (odd N).
    for j in range(n_lenses, len(flat_axes)):
        flat_axes[j].axis("off")
    if not any_drawn:
        plt.close(fig)
        return False
    fig.suptitle("FPS overview — all lenses", fontsize=14)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return True
