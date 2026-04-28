"""Plot per-(pipeline, n, image-size) RAM and VRAM usage from a benchmark run.

Two side-by-side horizontal-bar panels (VRAM, RAM) on a tall portrait figure.
Pipelines are grouped by detector mode along the left edge; within each pipeline
group there is one bar per (n, image-size) combination, colored by image size.

Usage:
    # Either a run directory (preferred) or a results.csv path works.
    uv run python plot_ram_and_vram_usage.py benchmark_results/2026-04-28_10-32-14
    uv run python plot_ram_and_vram_usage.py results.csv -o results_ram_and_vram_usage.png
"""

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Patch

MB = 1024 * 1024
MODE_ORDER = ("BINARY", "MULTI_CLASS", "COUNT", "BOUNDING_BOX")
NUMERIC_COLUMNS = ("total_vram_bytes", "total_ram_bytes")
PIPELINE_GAP = 1.0
MODE_GAP = 3.4
BAR_DY = 1.0


def load_rows(path: Path) -> list[dict]:
    """Read the benchmark CSV and coerce numeric columns."""
    rows: list[dict] = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            r["n"] = int(r["n"]) if r["n"] not in ("", None) else None
            r["image_width"] = int(r["image_width"])
            r["image_height"] = int(r["image_height"])
            for k in NUMERIC_COLUMNS:
                r[k] = int(r[k]) if r[k] not in ("", None) else 0
            rows.append(r)
    return rows


def short_name(pipeline: str) -> str:
    """Trim well-known long prefixes/suffixes off pipeline names for compact labels.

    The trimmed pieces (`generic-cached-timm-` / `multiclass-generic-cached-timm-`
    prefixes; `-calibrated-mlp` / `-calibrated-smoothed-mlp` suffixes) are
    boilerplate that's implied by the detector mode shown alongside each label.
    """
    name = pipeline
    for prefix in ("multiclass-generic-cached-timm-", "generic-cached-timm-"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    for suffix in ("-calibrated-smoothed-mlp", "-calibrated-mlp"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name


def image_size_palette(rows: list[dict]) -> dict[tuple[int, int], tuple]:
    """Return {(w, h): rgba} sampled from viridis, ordered by image area (small -> dark)."""
    sizes = sorted({(r["image_width"], r["image_height"]) for r in rows}, key=lambda wh: wh[0] * wh[1])
    cmap = plt.get_cmap("viridis")
    if len(sizes) == 1:
        return {sizes[0]: cmap(0.5)}
    return {sz: cmap(0.15 + 0.7 * (i / (len(sizes) - 1))) for i, sz in enumerate(sizes)}


def build_layout(rows: list[dict]) -> dict:
    """Group rows by (mode, pipeline) and assign y-positions for plotting.

    Returns a dict with three lists -- bars (one per data row), pipeline_groups
    (one per distinct pipeline within a mode, used for left-gutter labels and
    spans), and mode_groups (one per distinct mode, used for bold headers).
    """
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        grouped[(r["mode"], r["pipeline"])].append(r)

    keys = sorted(
        grouped.keys(),
        key=lambda k: (MODE_ORDER.index(k[0]) if k[0] in MODE_ORDER else 99, k[1]),
    )
    palette = image_size_palette(rows)

    bars: list[dict] = []
    pipeline_groups: list[dict] = []
    mode_groups: list[dict] = []

    y = 0.0
    last_mode: str | None = None
    mode_top: float | None = None

    for (mode, pipeline) in keys:
        if last_mode is not None and mode != last_mode:
            mode_groups.append({"mode": last_mode, "y_top": mode_top, "y_bottom": y + BAR_DY - PIPELINE_GAP})
            y -= MODE_GAP
            mode_top = None
        elif last_mode is not None:
            y -= PIPELINE_GAP

        if mode_top is None:
            mode_top = y

        rows_for_pipeline = sorted(
            grouped[(mode, pipeline)],
            key=lambda r: ((r["n"] if r["n"] is not None else -1), r["image_width"] * r["image_height"]),
        )
        pipeline_top = y
        for r in rows_for_pipeline:
            n_str = "—" if r["n"] is None else f"n={r['n']}"
            bars.append({
                "y": y,
                "label": f"{n_str} ({r['image_width']}x{r['image_height']})",
                "color": palette[(r["image_width"], r["image_height"])],
                "vram": r["total_vram_bytes"] / MB,
                "ram": r["total_ram_bytes"] / MB,
            })
            y -= BAR_DY
        pipeline_bottom = y + BAR_DY
        pipeline_groups.append({
            "mode": mode,
            "pipeline": pipeline,
            "y_center": (pipeline_top + pipeline_bottom) / 2,
            "y_top": pipeline_top,
            "y_bottom": pipeline_bottom,
        })
        last_mode = mode

    if last_mode is not None:
        mode_groups.append({"mode": last_mode, "y_top": mode_top, "y_bottom": y + BAR_DY})

    return {"bars": bars, "pipeline_groups": pipeline_groups, "mode_groups": mode_groups, "palette": palette}


def plot_panel(ax, layout: dict, kind: str) -> None:
    """Render one horizontal-bar panel for `kind` ('vram' or 'ram')."""
    bars = layout["bars"]
    ys = [b["y"] for b in bars]
    vals = [b[kind] for b in bars]
    colors = [b["color"] for b in bars]

    ax.barh(ys, vals, color=colors, edgecolor="white", height=0.85)
    ax.set_yticks(ys)
    ax.set_yticklabels([b["label"] for b in bars], fontsize=8)
    ax.set_xlabel(f"total {kind.upper()} (MB)")
    ax.set_title(kind.upper())
    ax.grid(axis="x", linestyle=":", alpha=0.4)
    # Leave room above the topmost bar for the mode header on the first section.
    ax.set_ylim(min(ys) - 0.7, max(ys) + 3.2)

    xmax = max(vals) if vals else 1
    for y, v in zip(ys, vals):
        ax.text(v + xmax * 0.01, y, f"{v:.0f}", va="center", fontsize=7)
    ax.set_xlim(0, xmax * 1.12)


def annotate_section_headers(left_ax, layout: dict, all_axes) -> None:
    """Render mode and pipeline section headers in the leftmost gutter.

    Pipeline names are right-aligned with the n=X (WxH) tick labels; mode
    headers sit above them in larger bold type. Divider lines run across both
    panels to demarcate modes.
    """
    # Pipeline headers: medium semibold, in the left gutter just above each
    # pipeline's bar group, right-aligned with the n=X (WxH) tick labels.
    # The horizontal offset (-0.025) keeps the text from kissing the axis line.
    for grp in layout["pipeline_groups"]:
        left_ax.text(
            -0.025, grp["y_top"] + 0.85, short_name(grp["pipeline"]),
            transform=left_ax.get_yaxis_transform(),
            ha="right", va="center", fontsize=10, fontweight="semibold",
            color="#444444", clip_on=False,
        )
    # Mode headers: large bold, in the gutter above the first pipeline header
    # of each mode.
    for grp in layout["mode_groups"]:
        left_ax.text(
            -0.025, grp["y_top"] + 2.25, grp["mode"],
            transform=left_ax.get_yaxis_transform(),
            ha="right", va="bottom", fontsize=13, fontweight="bold",
            color="#1a1a1a", clip_on=False,
        )
    # Divider lines above each mode header except the first. Positioned midway
    # between the previous mode's last bar and the next mode's header so the
    # vertical padding above and below the line feels balanced.
    for grp in layout["mode_groups"][1:]:
        line_y = grp["y_top"] + 3.1
        for ax in all_axes:
            ax.axhline(y=line_y, color="#888888", linewidth=1.0, clip_on=False)


def add_size_legend(fig, palette: dict[tuple[int, int], tuple]) -> None:
    """Add a single figure-level legend mapping bar color to image size."""
    handles = [Patch(facecolor=color, label=f"{w}x{h} ({w*h/1e6:.2f} MP)")
               for (w, h), color in palette.items()]
    fig.legend(handles=handles, title="image size", loc="upper right", fontsize=9, title_fontsize=9)


def resolve_csv_and_meta(input_path: Path) -> tuple[Path, dict]:
    """Accept either a run directory or a results.csv path; return (csv_path, run_metadata).

    `run_metadata` is the parsed run_metadata.json dict if present alongside the CSV,
    otherwise an empty dict.
    """
    if input_path.is_dir():
        csv_path = input_path / "results.csv"
        if not csv_path.exists():
            raise SystemExit(f"No results.csv in {input_path}")
    else:
        csv_path = input_path
    meta_path = csv_path.parent / "run_metadata.json"
    metadata: dict = {}
    if meta_path.exists():
        with open(meta_path) as f:
            metadata = json.load(f)
    return csv_path, metadata


MAIN_TITLE: str = "Edge Endpoint RAM and VRAM usage"


def _short_sha(image_id: str | None) -> str:
    """Return the 7-char digest from either a bare `sha256:...` or a full `repo@sha256:...` ref."""
    if not image_id:
        return ""
    if "@sha256:" in image_id:
        return image_id.split("@sha256:", 1)[1][:7]
    if image_id.startswith("sha256:"):
        return image_id[len("sha256:") :][:7]
    return image_id[:7]


def subtitle_from_metadata(meta: dict, csv_path: Path) -> str:
    """Build a one-line subtitle from `run_metadata.json` (device, time, image digests)."""
    if not meta:
        return csv_path.name
    parts: list[str] = []
    if meta.get("device_name"):
        parts.append(meta["device_name"])
    if meta.get("run_started_at"):
        parts.append(meta["run_started_at"][:16].replace("T", " "))
    edge_sha = _short_sha(meta.get("edge_endpoint_image_id"))
    if edge_sha:
        parts.append(f"edge-endpoint @ {edge_sha}")
    inf_sha = _short_sha(meta.get("inference_server_image_id"))
    if inf_sha:
        parts.append(f"inference-server @ {inf_sha}")
    return "  \u2022  ".join(parts) or csv_path.name


def default_output_path(input_path: Path, csv_path: Path) -> Path:
    """Pick an output PNG location -- inside the run dir if input was a dir, next to the CSV otherwise."""
    if input_path.is_dir():
        return input_path / "ram_and_vram_usage.png"
    return csv_path.with_name(csv_path.stem + "_ram_and_vram_usage.png")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path,
                        help="Path to a benchmark run directory or directly to a results.csv.")
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="Path to save the figure. Defaults to <run-dir>/ram_and_vram_usage.png (or <csv-stem>_ram_and_vram_usage.png next to a CSV).")
    parser.add_argument("--show", action="store_true",
                        help="Open the figure in an interactive window instead of saving it (requires a display).")
    return parser.parse_args()


def render(input_path: Path, output: Path | None = None, show: bool = False) -> Path | None:
    """Render the figure from a run directory or results.csv. Returns the saved PNG path
    (or None when `show=True`). Importable so other scripts (e.g. the measurement script)
    can plot without shelling out.
    """
    csv_path, metadata = resolve_csv_and_meta(input_path)
    rows = load_rows(csv_path)
    if not rows:
        raise SystemExit(f"No data rows in {csv_path}")
    layout = build_layout(rows)

    n_bars = len(layout["bars"])
    height = max(6.0, 0.40 * n_bars + 1.8)
    fig, axes = plt.subplots(1, 2, figsize=(14, height), sharey=True)
    plot_panel(axes[0], layout, "vram")
    plot_panel(axes[1], layout, "ram")
    annotate_section_headers(axes[0], layout, axes)
    add_size_legend(fig, layout["palette"])

    fig.suptitle(MAIN_TITLE, fontsize=15, fontweight="bold", y=0.985)
    fig.text(0.5, 0.955, subtitle_from_metadata(metadata, csv_path),
             ha="center", va="top", fontsize=10, color="#444")
    notes = (metadata.get("notes") or "").strip()
    top = 0.92
    if notes:
        fig.text(0.5, 0.928, f"Notes: {notes}", ha="center", va="top",
                 fontsize=9, color="#666", style="italic")
        top = 0.905
    fig.tight_layout(rect=(0, 0, 1, top))
    fig.subplots_adjust(left=0.30, wspace=0.06)

    if show:
        plt.show()
        return None
    out = output or default_output_path(input_path, csv_path)
    fig.savefig(out, dpi=120)
    plt.close(fig)
    print(f"Saved to {out}")
    return out


def main() -> None:
    args = parse_args()
    render(args.input, args.output, args.show)


if __name__ == "__main__":
    main()
