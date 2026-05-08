"""Per-run + cross-run summaries and plots from the JSONL request log.

Each (lens, camera) is treated as an independent process and gets its own
FPS-over-time plot + summary row. RPS isn't reported — for the chained
`bbox_to_binary` lens it's just FPS × (1 + n), which adds noise without
information about the lens-level throughput we actually care about.

The system_utilization plot still uses parse_load_test_logs.parse_log_file
to read the cpu/gpu time series the SystemMonitor writes.
"""

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from parse_load_test_logs import parse_log_file

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
        hit = None  # saturate / no target
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
    """Per-(lens, camera) summary + FPS plots, plus system utilization plot."""
    events = _read_request_events(log_file, start_ts=main_start_ts)

    # Build (lens, camera) buckets and the per-lens target_fps lookup.
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
    _write_run_md(run_dir / "summary.md", summary)
    _plot_run(run_dir, by_camera, target_by_lens, main_start_ts, log_file)
    return summary


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


def _write_run_md(path: Path, summary: dict[str, Any]) -> None:
    meta = summary["meta"]
    lines = [
        f"# Run {meta.get('run_index')}",
        "",
        f"- **lens_n**: `{meta.get('lens_n', {})}`",
        f"- **duration**: `{meta.get('duration_seconds')}s`  "
        f"**warmup**: `{meta.get('warmup_seconds')}s`",
        "",
        "Each row is one camera process. `Hit` = achieved FPS within "
        f"{int(_FPS_HIT_TOLERANCE * 100)}% of target. `target = saturate` means "
        "no pacing (target_fps: 0); no Hit verdict in that case.",
        "",
        "| Lens | Camera | Frames | Errors | FPS | Target | Hit | p50 (s) | p95 (s) |",
        "|---|---:|---:|---:|---:|---:|:---:|---:|---:|",
    ]
    for cam in summary["cameras"]:
        lines.append(
            f"| {cam['lens_name']} | {cam['camera']} | {cam['total_frames']} | "
            f"{cam['errors']} | {cam['achieved_fps']:.1f} | "
            f"{_target_label(cam['target_fps'])} | {_hit_label(cam['hit_target'])} | "
            f"{cam['latency_p50_sec']:.3f} | {cam['latency_p95_sec']:.3f} |"
        )
    path.write_text("\n".join(lines) + "\n")


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
    _plot_system_util(plots_dir, log_file)


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


def _plot_system_util(plots_dir: Path, log_file: Path) -> None:
    try:
        res = parse_log_file(str(log_file))
    except RuntimeError:
        return
    fig, ax = plt.subplots(figsize=(10, 4))
    plotted = False
    for label, series, color in [
        ("GPU compute %", res.gpu_by_time, "tab:red"),
        ("VRAM %", res.vram_by_time, "tab:purple"),
        ("CPU %", res.cpu_by_time, "tab:blue"),
        ("RAM %", res.ram_by_time, "tab:green"),
    ]:
        items = sorted(series.items())
        if not items:
            continue
        ax.plot([t for t, _ in items], [v for _, v in items], label=label, color=color)
        plotted = True
    if plotted:
        ax.set_ylim(0, 105)
        ax.set_ylabel("%")
        ax.set_xlabel("time")
        ax.set_title("System utilization")
        ax.legend(loc="upper right")
        ax.grid(True, alpha=0.3)
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(plots_dir / "system_utilization.png", dpi=120)
    plt.close(fig)


def write_top_level(out_root: Path, summaries: list[dict[str, Any]]) -> None:
    """Cross-run table: per-run rows with mean per-lens FPS + worst-case Hit."""
    payload = {"runs": summaries}
    (out_root / "summary.json").write_text(json.dumps(payload, indent=2))

    lines = ["# Benchmark summary", ""]
    if not summaries:
        lines.append("(no runs)")
        (out_root / "summary.md").write_text("\n".join(lines) + "\n")
        return

    lens_names = sorted({c["lens_name"] for s in summaries for c in s.get("cameras", [])})
    per_lens_cols = [c for lens in lens_names for c in (f"{lens} FPS", f"{lens} Hit")]
    header = ["run", "lens_n"] + per_lens_cols
    lines.append(
        "Per-lens FPS = mean across that lens's camera processes. "
        f"Hit = `yes` if every camera in the lens hit ≥{int(_FPS_HIT_TOLERANCE * 100)}% "
        "of its target; `no` otherwise; `—` for saturate-mode lenses."
    )
    lines.append("")
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
                hit_label = "—"
            elif any(h is False for h in hits):
                hit_label = "no"
            else:
                hit_label = "yes"
            cells.append(f"{mean_fps:.1f}")
            cells.append(hit_label)
        lines.append("| " + " | ".join(cells) + " |")
    (out_root / "summary.md").write_text("\n".join(lines) + "\n")
