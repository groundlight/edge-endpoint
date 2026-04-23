"""Plot a resource-benchmark CSV produced by `measure_detector_resource_utilization.py`.

Renders a 3x2 figure with:
- Row 1: pipelines ranked by mean VRAM and RAM (stacked primary + oodd, with min/max range bars).
- Row 2: total VRAM and RAM vs `n`, one line per (pipeline, image size), restricted to pipelines whose `n` varies.
- Row 3: total VRAM and RAM vs image megapixels, one line per (pipeline, n), restricted to pipelines whose image size varies.

Usage:
    uv run python plot_resource_benchmark.py benchmark_results/resource_benchmark_20260423_214405.csv
    uv run python plot_resource_benchmark.py results.csv -o results.png
"""

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt

MB = 1024 * 1024
NUMERIC_COLUMNS = (
    "primary_vram_bytes", "oodd_vram_bytes", "total_vram_bytes",
    "primary_ram_bytes", "oodd_ram_bytes", "total_ram_bytes",
)
PRIMARY_COLOR = "#4A90D9"
OODD_COLOR = "#A0C4EC"


def load_rows(path: Path) -> list[dict]:
    """Read the benchmark CSV and coerce numeric / boolean columns. Drops not-ready rows."""
    rows: list[dict] = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if r.get("ready", "").strip().lower() != "true":
                continue
            r["n"] = int(r["n"]) if r["n"] not in ("", None) else None
            r["image_width"] = int(r["image_width"])
            r["image_height"] = int(r["image_height"])
            for key in NUMERIC_COLUMNS:
                r[key] = int(r[key]) if r[key] not in ("", None) else 0
            rows.append(r)
    return rows


def short_name(pipeline: str, mode: str) -> str:
    """Trim well-known prefixes off pipeline names so they fit on axis labels and legends."""
    name = pipeline
    for prefix in ("multiclass-generic-cached-timm-", "generic-cached-timm-"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return f"[{mode}] {name}"


def plot_pipeline_ranking(ax, rows: list[dict], kind: str) -> None:
    """Stacked horizontal bar of mean primary + oodd, sorted by total, with min/max range bars."""
    by_pipeline: dict[tuple[str, str], list[tuple[int, int, int]]] = defaultdict(list)
    for r in rows:
        by_pipeline[(r["mode"], r["pipeline"])].append(
            (r[f"primary_{kind}_bytes"], r[f"oodd_{kind}_bytes"], r[f"total_{kind}_bytes"])
        )

    items = []
    for (mode, pipeline), vals in by_pipeline.items():
        prim_mean = sum(p for p, _, _ in vals) / len(vals) / MB
        oodd_mean = sum(o for _, o, _ in vals) / len(vals) / MB
        total_mean = sum(t for _, _, t in vals) / len(vals) / MB
        total_min = min(t for _, _, t in vals) / MB
        total_max = max(t for _, _, t in vals) / MB
        items.append((mode, pipeline, prim_mean, oodd_mean, total_mean, total_min, total_max, len(vals)))
    items.sort(key=lambda x: x[4])

    labels = [f"{short_name(p, m)} ({c} cfg)" for m, p, *_, c in items]
    prim = [it[2] for it in items]
    oodd = [it[3] for it in items]
    totals = [it[4] for it in items]
    # xerr is [lower_distance, upper_distance] from each mean total.
    err_lo = [it[4] - it[5] for it in items]
    err_hi = [it[6] - it[4] for it in items]

    y = list(range(len(items)))
    ax.barh(y, prim, color=PRIMARY_COLOR, label="primary")
    ax.barh(y, oodd, left=prim, color=OODD_COLOR, label="oodd")
    ax.errorbar(totals, y, xerr=[err_lo, err_hi], fmt="none", ecolor="black", capsize=3, linewidth=1)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel(f"{kind.upper()} (MB)")
    ax.set_title(f"{kind.upper()} per pipeline (mean, range)")
    ax.legend(loc="lower right", fontsize=8)
    xmax = max((t + (it[6] - it[4]) for t, it in zip(totals, items)), default=0)
    for yi, t in zip(y, totals):
        ax.text(t + xmax * 0.01, yi, f"{t:.0f}", va="center", fontsize=7)
    ax.set_xlim(0, xmax * 1.15 if xmax else 1)
    ax.grid(axis="x", linestyle=":", alpha=0.5)


def _palette(keys: list) -> dict:
    """Stable color per key so the same pipeline keeps its color across panels."""
    cmap = plt.get_cmap("tab20")
    return {k: cmap(i % cmap.N) for i, k in enumerate(keys)}


def plot_effect_of_n(ax, rows: list[dict], kind: str) -> None:
    """Lines of total {kind} vs n, one per (pipeline, image size). Skips series that don't vary n."""
    series: dict[tuple[str, str, int, int], list[tuple[int, float]]] = defaultdict(list)
    for r in rows:
        if r["n"] is None:
            continue
        key = (r["mode"], r["pipeline"], r["image_width"], r["image_height"])
        series[key].append((r["n"], r[f"total_{kind}_bytes"] / MB))

    plotted = [(k, sorted(v)) for k, v in series.items() if len({n for n, _ in v}) >= 2]
    colors = _palette([k for k, _ in plotted])
    for key, points in plotted:
        mode, pipeline, w, h = key
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        ax.plot(xs, ys, marker="o", color=colors[key], label=f"{short_name(pipeline, mode)} @ {w}x{h}")

    ax.set_xlabel("n (max_count / max_num_bboxes / num_classes)")
    ax.set_ylabel(f"total {kind.upper()} (MB)")
    ax.set_title(f"{kind.upper()} vs n")
    ax.grid(linestyle=":", alpha=0.5)
    if plotted:
        ax.legend(loc="best", fontsize=7)
    else:
        ax.text(0.5, 0.5, "No pipeline varies `n` in this dataset", ha="center", va="center", transform=ax.transAxes)


def plot_effect_of_image_size(ax, rows: list[dict], kind: str) -> None:
    """Lines of total {kind} vs image megapixels, one per (pipeline, n). Skips series with only one image size."""
    series: dict[tuple[str, str, int | None], list[tuple[float, int, int, float]]] = defaultdict(list)
    for r in rows:
        key = (r["mode"], r["pipeline"], r["n"])
        mpix = (r["image_width"] * r["image_height"]) / 1e6
        series[key].append((mpix, r["image_width"], r["image_height"], r[f"total_{kind}_bytes"] / MB))

    plotted = [
        (k, sorted(v))
        for k, v in series.items()
        if len({(w, h) for _, w, h, _ in v}) >= 2
    ]
    colors = _palette([k for k, _ in plotted])
    for key, points in plotted:
        mode, pipeline, n = key
        xs = [p[0] for p in points]
        ys = [p[3] for p in points]
        n_label = "" if n is None else f", n={n}"
        ax.plot(xs, ys, marker="o", color=colors[key], label=f"{short_name(pipeline, mode)}{n_label}")

    ax.set_xlabel("image size (megapixels)")
    ax.set_ylabel(f"total {kind.upper()} (MB)")
    ax.set_title(f"{kind.upper()} vs image size")
    ax.grid(linestyle=":", alpha=0.5)
    if plotted:
        ax.legend(loc="best", fontsize=7)
    else:
        ax.text(0.5, 0.5, "No pipeline varies image size in this dataset", ha="center", va="center", transform=ax.transAxes)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv", type=Path, help="Path to a resource-benchmark CSV.")
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="Path to save the figure. Defaults to <csv-without-extension>.png next to the input.")
    parser.add_argument("--show", action="store_true",
                        help="Open the figure in an interactive window instead of saving it (requires a display).")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = load_rows(args.csv)
    if not rows:
        raise SystemExit(f"No ready=True rows in {args.csv}")

    fig, axes = plt.subplots(3, 2, figsize=(15, 14))
    plot_pipeline_ranking(axes[0][0], rows, "vram")
    plot_pipeline_ranking(axes[0][1], rows, "ram")
    plot_effect_of_n(axes[1][0], rows, "vram")
    plot_effect_of_n(axes[1][1], rows, "ram")
    plot_effect_of_image_size(axes[2][0], rows, "vram")
    plot_effect_of_image_size(axes[2][1], rows, "ram")
    fig.suptitle(f"Edge resource benchmark: {args.csv.name} ({len(rows)} ready detectors)", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.97))

    if args.show:
        plt.show()
    else:
        out = args.output or args.csv.with_suffix(".png")
        fig.savefig(out, dpi=120)
        print(f"Saved to {out}")


if __name__ == "__main__":
    main()
