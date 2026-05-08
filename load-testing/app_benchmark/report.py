"""Per-run + cross-run summaries and plots from the JSONL request log.

Format-compatible with parse_load_test_logs.parse_log_file (used here for
time-series plots) — workers and SystemMonitor write the same JSONL schema.
The per-lens summary stats are computed here directly because lens types
have different per-client expected RPS, which the load-test summarizer
can't represent in a single number.
"""

import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from parse_load_test_logs import parse_log_file


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


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, int(pct * len(sorted_values)))
    return sorted_values[idx]


def _summarize_events(events: list[dict]) -> dict[str, Any]:
    total = len(events)
    errors = sum(1 for e in events if not e.get("success", True))
    latencies = sorted(float(e.get("latency", 0)) for e in events)
    if events:
        ts = [float(e["ts"]) for e in events]
        duration = max(ts) - min(ts)
    else:
        duration = 0.0
    return {
        "total_requests": total,
        "errors": errors,
        "duration_seconds": round(duration, 2),
        "achieved_rps": round(total / duration, 2) if duration > 0 else 0.0,
        "latency_p50_sec": round(_percentile(latencies, 0.5), 4),
        "latency_p95_sec": round(_percentile(latencies, 0.95), 4),
    }


def write_run_artifacts(
    run_dir: Path,
    log_file: Path,
    run_meta: dict[str, Any],
    main_start_ts: float,
) -> dict[str, Any]:
    """Compute per-lens + aggregate summary, plot, and write summary.{json,md}."""
    events = _read_request_events(log_file, start_ts=main_start_ts)
    by_lens: dict[str, list[dict]] = {}
    for ev in events:
        by_lens.setdefault(ev.get("lens_name", "_"), []).append(ev)

    summary: dict[str, Any] = {
        "meta": run_meta,
        "aggregate": _summarize_events(events),
        "lenses": {lens: _summarize_events(evs) for lens, evs in sorted(by_lens.items())},
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    _write_run_md(run_dir / "summary.md", summary)
    _plot_run(run_dir, log_file)
    return summary


def _write_run_md(path: Path, summary: dict[str, Any]) -> None:
    meta = summary["meta"]
    agg = summary["aggregate"]
    lines = [
        f"# Run {meta.get('run_index')}",
        "",
        f"- **lens_n**: `{meta.get('lens_n', {})}`",
        f"- **image_size**: `{meta.get('image_size')}`  **target_fps**: `{meta.get('target_fps')}`",
        f"- **duration**: `{meta.get('duration_seconds')}s`",
        "",
        f"**Aggregate**: {agg['total_requests']} requests · {agg['errors']} errors · "
        f"{agg['achieved_rps']:.1f} RPS · p50={agg['latency_p50_sec']:.3f}s · "
        f"p95={agg['latency_p95_sec']:.3f}s",
        "",
        "| Lens | Requests | Errors | RPS | p50 (s) | p95 (s) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for lens, stats in summary["lenses"].items():
        lines.append(
            f"| {lens} | {stats['total_requests']} | {stats['errors']} | "
            f"{stats['achieved_rps']:.1f} | {stats['latency_p50_sec']:.3f} | "
            f"{stats['latency_p95_sec']:.3f} |"
        )
    path.write_text("\n".join(lines) + "\n")


def _plot_run(run_dir: Path, log_file: Path) -> None:
    plots_dir = run_dir / "plots"
    plots_dir.mkdir(exist_ok=True)
    try:
        res = parse_log_file(str(log_file))
    except RuntimeError:
        return  # no request events — skip plots

    if res.requests_by_time:
        fig, ax = plt.subplots(figsize=(10, 4))
        items = sorted(res.requests_by_time.items())
        ax.plot([t for t, _ in items], [v for _, v in items], color="tab:blue", label="requests/sec")
        ax.set_title("Requests per second")
        ax.set_ylabel("RPS")
        ax.set_xlabel("time")
        ax.grid(True, alpha=0.3)
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(plots_dir / "requests_per_second.png", dpi=120)
        plt.close(fig)

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
    """Cross-run summary: one row per run with the lens-n vector and aggregate RPS."""
    payload = {"runs": summaries}
    (out_root / "summary.json").write_text(json.dumps(payload, indent=2))

    lines = ["# Benchmark summary", ""]
    if not summaries:
        lines.append("(no runs)")
        (out_root / "summary.md").write_text("\n".join(lines) + "\n")
        return

    lens_names = sorted({lens for s in summaries for lens in s.get("lenses", {})})
    header = ["run", "lens_n", "agg RPS", "agg errors"] + [f"{l} RPS" for l in lens_names]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")
    for s in summaries:
        meta = s["meta"]
        agg = s["aggregate"]
        cells = [
            str(meta.get("run_index", "?")),
            f"`{meta.get('lens_n', {})}`",
            f"{agg['achieved_rps']:.1f}",
            str(agg["errors"]),
        ]
        for lens in lens_names:
            stats = s.get("lenses", {}).get(lens)
            cells.append(f"{stats['achieved_rps']:.1f}" if stats else "—")
        lines.append("| " + " | ".join(cells) + " |")
    (out_root / "summary.md").write_text("\n".join(lines) + "\n")
