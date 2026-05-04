"""Benchmark per-detector VRAM and RAM consumption on a running Edge Endpoint."""

import argparse
import csv
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml
from groundlight import Detector, ExperimentalApi

from constants import SUPPORTED_DETECTOR_MODES
import groundlight_helpers as glh
import image_helpers as imgh
import plot_ram_and_vram_usage

NAME_PREFIX: str = "edge-bench"
GROUP_NAME: str = "Edge Benchmarking"
RESULTS_DIR: Path = Path(__file__).parent / "benchmark_results"
SNAPSHOT_YAML_NAME: str = "benchmark_pipelines.yaml"
METADATA_FILE_NAME: str = "run_metadata.json"
RESULTS_FILE_NAME: str = "results.csv"
CSV_FIELDS: list[str] = [
    "mode", "n", "pipeline", "image_width", "image_height", "detector_id", "ready",
    "primary_vram_bytes", "oodd_vram_bytes", "total_vram_bytes",
    "primary_ram_bytes", "oodd_ram_bytes", "total_ram_bytes",
    "system_vram_used_bytes", "system_vram_total_bytes",
    "system_ram_used_bytes", "system_ram_total_bytes",
]
DEFAULT_WARMUP_DURATION_SEC: float = 60.0


def _parse_image_sizes(raw: Any, mode: str) -> list[tuple[int, int]]:
    """Validate and normalize `image_sizes:` from a mode block into a list of (w, h) tuples."""
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{mode}.image_sizes must be a non-empty list of [width, height] pairs")
    sizes: list[tuple[int, int]] = []
    for pair in raw:
        if not (isinstance(pair, list) and len(pair) == 2 and all(isinstance(x, int) for x in pair)):
            raise ValueError(f"{mode}.image_sizes entries must be [width, height] int pairs (got {pair!r})")
        sizes.append((pair[0], pair[1]))
    return sizes


def _parse_n_list(raw: Any, mode: str) -> list[int]:
    """Validate and normalize `n:` from a mode block into a list of ints."""
    if not isinstance(raw, list) or not raw or not all(isinstance(x, int) for x in raw):
        raise ValueError(f"{mode}.n must be a non-empty list of ints (got {raw!r})")
    return raw


def load_detector_specs(path: Path) -> list[dict]:
    """Parse the YAML and expand each mode block into the cartesian product of n x image_size x pipeline.

    Each returned dict matches the kwargs of `glh.provision_detector`, so callers can
    splat it directly: `glh.provision_detector(gl_cloud, **spec, ...)`.
    """
    with open(path) as f:
        data = yaml.safe_load(f) or {}

    specs: list[dict] = []

    for mode, block in data.items():
        if mode not in SUPPORTED_DETECTOR_MODES:
            raise ValueError(f"Unsupported detector mode: {mode}. Supported: {sorted(SUPPORTED_DETECTOR_MODES)}")

        # Bare list of pipeline names is shorthand for {pipelines: [...]}; image_sizes still required at script level.
        if isinstance(block, list):
            block = {"pipelines": block}
        if not isinstance(block, dict):
            raise ValueError(f"{mode} must be a mapping or a bare list of pipeline names (got {type(block).__name__})")

        unknown_keys = set(block) - {"n", "image_sizes", "pipelines"}
        if unknown_keys:
            raise ValueError(f"{mode} has unknown keys: {sorted(unknown_keys)}")

        pipelines = block.get("pipelines") or []
        if not pipelines or not all(isinstance(p, str) for p in pipelines):
            raise ValueError(f"{mode}.pipelines must be a non-empty list of pipeline-config strings")

        if "image_sizes" not in block:
            raise ValueError(f"{mode}.image_sizes is required (a non-empty list of [width, height] pairs).")
        image_sizes = _parse_image_sizes(block["image_sizes"], mode)

        if mode == "BINARY":
            if "n" in block:
                raise ValueError("BINARY does not accept `n` (its label space is fixed at 2).")
            n_values: list[Optional[int]] = [None]
        else:
            n_values = (
                list(_parse_n_list(block["n"], mode))
                if "n" in block
                else [glh.default_n_for_mode(mode)]
            )

        for pipeline in pipelines:
            for n in n_values:
                for width, height in image_sizes:
                    specs.append({
                        "detector_mode": mode,
                        "edge_pipeline_config": pipeline,
                        "n": n,
                        "image_width": width,
                        "image_height": height,
                    })

    return specs


SpecKey = tuple[str, str, Optional[int], int, int]


def spec_key(spec: dict) -> SpecKey:
    """Return a hashable identity tuple for a detector spec (matches CSV row identity)."""
    return (
        spec["detector_mode"],
        spec["edge_pipeline_config"],
        spec["n"],
        spec["image_width"],
        spec["image_height"],
    )


def load_completed(path: Path) -> set[SpecKey]:
    """Read an existing results CSV and return the set of spec-keys already recorded."""
    completed: set[SpecKey] = set()
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            n_raw = row.get("n", "")
            n = int(n_raw) if n_raw not in ("", None) else None
            completed.add((row["mode"], row["pipeline"], n, int(row["image_width"]), int(row["image_height"])))
    return completed


def fetch_resources(gl: ExperimentalApi) -> dict:
    """Fetch /status/resources.json from the Edge Endpoint."""
    base = gl.endpoint.replace("/device-api", "")
    return glh.call_api(base + "/status/resources.json", {})


def fetch_metrics(gl: ExperimentalApi) -> dict:
    """Fetch /status/metrics.json from the Edge Endpoint."""
    base = gl.endpoint.replace("/device-api", "")
    return glh.call_api(base + "/status/metrics.json", {})


def extract_image_ids(metrics: dict) -> tuple[Optional[str], Optional[str]]:
    """Pull the edge-endpoint and inference-server container image IDs out of metrics.json.

    `k3s_stats.container_images` is itself a JSON-encoded string of
    {pod_name: {container_name: image_id}} (see app/metrics/system_metrics.py).
    Either image ID may be None if the corresponding pod isn't running yet.
    """
    raw = (metrics.get("k3s_stats") or {}).get("container_images")
    if not raw:
        return None, None
    try:
        containers = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return None, None
    edge_id: Optional[str] = None
    inf_id: Optional[str] = None
    for container_map in (containers or {}).values():
        for container_name, image_id in (container_map or {}).items():
            if container_name == "edge-endpoint" and edge_id is None:
                edge_id = image_id
            elif container_name == "inference-server" and inf_id is None:
                inf_id = image_id
    return edge_id, inf_id


def detector_resource_row(resources: dict, detector_id: str) -> Optional[dict]:
    """Return the per-detector entry from /status/resources.json, or None if not present."""
    for det in resources.get("detectors") or []:
        if det.get("detector_id") == detector_id:
            return det
    return None


def write_run_metadata(
    path: Path,
    *,
    device_name: str,
    notes: Optional[str],
    run_started_at: str,
    edge_endpoint_image_id: Optional[str],
    inference_server_image_id: Optional[str],
) -> None:
    """Write run_metadata.json from scratch. Used at run-dir init."""
    payload = {
        "device_name": device_name,
        "notes": notes,
        "run_started_at": run_started_at,
        "edge_endpoint_image_id": edge_endpoint_image_id,
        "inference_server_image_id": inference_server_image_id,
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")


def update_image_ids(path: Path, edge_endpoint_image_id: Optional[str], inference_server_image_id: Optional[str]) -> None:
    """Backfill the two image-id fields in run_metadata.json without touching anything else."""
    with open(path) as f:
        data = json.load(f)
    data["edge_endpoint_image_id"] = edge_endpoint_image_id
    data["inference_server_image_id"] = inference_server_image_id
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def from_yaml_path(
    yaml_path: Path,
    device_name: str,
    notes: Optional[str],
) -> tuple[Path, list[dict], set[SpecKey]]:
    """Initialize a fresh run from a pipelines YAML.

    Creates the run directory, snapshots the YAML inside as
    `benchmark_pipelines.yaml`, writes `run_metadata.json` (image IDs as null
    -- callers backfill once connected to the edge endpoint), and initializes
    an empty `results.csv`. Returns `(run_dir, all_specs, completed=set())`.
    """
    RESULTS_DIR.mkdir(exist_ok=True)
    started_dt = datetime.now()
    run_dir = RESULTS_DIR / started_dt.strftime("%Y-%m-%d_%H-%M-%S")
    run_dir.mkdir()

    (run_dir / SNAPSHOT_YAML_NAME).write_text(yaml_path.read_text())

    with open(run_dir / RESULTS_FILE_NAME, "w", newline="") as f:
        csv.DictWriter(f, fieldnames=CSV_FIELDS).writeheader()

    write_run_metadata(
        run_dir / METADATA_FILE_NAME,
        device_name=device_name,
        notes=notes,
        run_started_at=started_dt.isoformat(timespec="seconds"),
        edge_endpoint_image_id=None,
        inference_server_image_id=None,
    )

    all_specs = load_detector_specs(yaml_path)
    print(f"Created new run directory: {run_dir}")
    print(f"Loaded {len(all_specs)} detector spec(s) from {yaml_path}")
    return run_dir, all_specs, set()


def from_runtime_dir(run_dir: Path) -> tuple[Path, list[dict], set[SpecKey]]:
    """Resume an existing run from its directory.

    Validates that the directory contains `benchmark_pipelines.yaml`,
    `results.csv`, and `run_metadata.json`. Loads the snapshotted YAML and the
    set of measurements already recorded in the CSV. Returns
    `(run_dir, all_specs, completed)`.
    """
    if not run_dir.is_dir():
        raise SystemExit(f"--resume target is not a directory: {run_dir}")
    snapshot_yaml = run_dir / SNAPSHOT_YAML_NAME
    results_file = run_dir / RESULTS_FILE_NAME
    metadata_file = run_dir / METADATA_FILE_NAME
    for required in (snapshot_yaml, results_file, metadata_file):
        if not required.exists():
            raise SystemExit(f"Resumed run directory is missing required file: {required}")

    all_specs = load_detector_specs(snapshot_yaml)
    completed = load_completed(results_file)
    print(f"Resuming run at {run_dir} ({len(completed)} measurement(s) already recorded)")
    return run_dir, all_specs, completed


def parse_args() -> argparse.Namespace:
    """Parse CLI args. Enforces that --resume is mutually exclusive with all run-config args."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pipelines", type=Path, nargs="?", default=None,
                        help="Path to YAML file listing pipelines to benchmark. Required for new runs; forbidden with --resume.")
    parser.add_argument("--device-name", type=str, default=None,
                        help="Short identifier for the edge device under test (e.g. 'jetson-orin-nx-tim-01'). Required for new runs; forbidden with --resume.")
    parser.add_argument("--notes", type=str, default=None,
                        help="Optional free-form notes about the run (power mode, ambient conditions, etc.). Forbidden with --resume.")
    parser.add_argument("--resume", type=Path, default=None,
                        help="Path to an existing run directory; already-recorded measurements are skipped. Mutually exclusive with the YAML, --device-name, --notes.")
    parser.add_argument("--batch-size", type=int, default=1,
                        help="Detectors configured on the edge endpoint per measurement batch.")
    parser.add_argument("--warmup-duration-sec", type=float, default=DEFAULT_WARMUP_DURATION_SEC,
                        help="How long to send inference requests to all batch detectors before measuring (seconds).")
    parser.add_argument("--training-timeout-sec", type=float, default=60 * 20,
                        help="Per-detector training timeout. Cloud trains concurrently, so total wall-time is bounded by the slowest single detector.")
    args = parser.parse_args()

    if args.resume:
        conflicts = []
        if args.pipelines is not None:
            conflicts.append("pipelines YAML")
        if args.device_name is not None:
            conflicts.append("--device-name")
        if args.notes is not None:
            conflicts.append("--notes")
        if conflicts:
            parser.error(
                f"--resume is mutually exclusive with: {', '.join(conflicts)}. "
                "The snapshotted YAML and run_metadata.json in the resumed directory define the run."
            )
    else:
        if args.pipelines is None:
            parser.error("pipelines YAML is required (or use --resume <run-dir>).")
        if args.device_name is None:
            parser.error("--device-name is required for new runs (or use --resume <run-dir>).")

    return args


def provision_all(
    gl_cloud: ExperimentalApi,
    specs: list[dict],
) -> list[Detector]:
    """Phase 1: get-or-create + prime every detector that isn't yet sufficiently trained."""
    print(f"\n=== Phase 1: provisioning {len(specs)} detector(s) ===")
    detectors: list[Detector] = []
    for spec in specs:
        detector = glh.provision_detector(
            gl_cloud=gl_cloud,
            detector_name_prefix=NAME_PREFIX,
            group_name=GROUP_NAME,
            wait_for_training=False,
            **spec,
        )
        print(f'Got or created {detector.id}')
        detectors.append(detector)
    return detectors


def wait_for_all_trained(
    gl_cloud: ExperimentalApi,
    detectors: list[Detector],
    *,
    training_timeout_sec: float,
) -> None:
    """Phase 2: wait for every detector's edge pipeline to finish training. Cloud training runs concurrently."""
    print(f"\n=== Phase 2: waiting for {len(detectors)} detector(s) to finish training ===")
    for detector in detectors:
        num_labels = glh.num_priming_labels_for_detector(detector)
        min_training_labels = int(num_labels * 0.75)
        glh.wait_for_edge_pipeline_trained(
            gl_cloud, detector, min_training_labels, timeout_sec=training_timeout_sec
        )


def measure_batch(
    gl: ExperimentalApi,
    batch_specs: list[dict],
    batch_detectors: list[Detector],
    warmup_duration_sec: float,
) -> list[dict]:
    """Configure the Edge Endpoint with this batch, send warmup inference requests, sample once, and return CSV rows.

    Warmup sends queries to all detectors in round-robin until the duration elapses, ensuring
    the allocator has settled before the snapshot is taken. `ready` is recorded but not gated on.
    """
    glh.configure_edge_endpoint(gl, batch_detectors)

    print(f"  Warming up for {warmup_duration_sec:.0f}s...")
    end_at = time.time() + warmup_duration_sec
    while time.time() < end_at:
        for spec, detector in zip(batch_specs, batch_detectors):
            image, _, _ = imgh.generate_random_image(detector, spec["image_width"], spec["image_height"])
            gl.submit_image_query(detector, image, **glh.IQ_KWARGS_FOR_NO_ESCALATION)

    readiness_map = gl.edge.get_detector_readiness()
    readiness_by_id = {d.id: bool(readiness_map.get(d.id, False)) for d in batch_detectors}
    resources = fetch_resources(gl)
    system = resources.get("system", {}) or {}
    system_vram = system.get("vram", {}) or {}
    system_ram = system.get("ram", {}) or {}

    rows: list[dict] = []
    for spec, detector in zip(batch_specs, batch_detectors):
        det_entry = detector_resource_row(resources, detector.id) or {}
        vram = det_entry.get("vram") or {}
        ram = det_entry.get("ram") or {}
        rows.append({
            "mode": spec["detector_mode"],
            "n": spec["n"] if spec["n"] is not None else "",
            "pipeline": spec["edge_pipeline_config"],
            "image_width": spec["image_width"],
            "image_height": spec["image_height"],
            "detector_id": detector.id,
            "ready": readiness_by_id.get(detector.id, False),
            "primary_vram_bytes": vram.get("primary_bytes"),
            "oodd_vram_bytes": vram.get("oodd_bytes"),
            "total_vram_bytes": vram.get("total_bytes"),
            "primary_ram_bytes": ram.get("primary_bytes"),
            "oodd_ram_bytes": ram.get("oodd_bytes"),
            "total_ram_bytes": ram.get("total_bytes"),
            "system_vram_used_bytes": system_vram.get("used_bytes"),
            "system_vram_total_bytes": system_vram.get("total_bytes"),
            "system_ram_used_bytes": system_ram.get("used_bytes"),
            "system_ram_total_bytes": system_ram.get("total_bytes"),
        })
    return rows


def main() -> None:
    """Run the benchmark end-to-end (or resume an existing run dir, when --resume is set)."""
    args = parse_args()

    if args.resume:
        run_dir, all_specs, completed = from_runtime_dir(args.resume)
    elif args.pipelines is not None:
        run_dir, all_specs, completed = from_yaml_path(args.pipelines, args.device_name, args.notes)
    else:
        # Defense-in-depth: parse_args() already requires exactly one of these.
        raise AssertionError("parse_args should have rejected this; either --resume or pipelines must be set")

    specs = [s for s in all_specs if spec_key(s) not in completed]
    results_file = run_dir / RESULTS_FILE_NAME
    print(f"{len(specs)} measurement(s) to perform of {len(all_specs)} in the YAML")

    if not specs:
        print("Nothing to do.")
        return

    gl = ExperimentalApi()
    glh.error_if_endpoint_is_cloud(gl)
    gl_cloud = ExperimentalApi(endpoint=glh.CLOUD_ENDPOINT_PROD)

    # Backfill container image IDs in run_metadata.json on new runs. Some IDs may
    # still be null at this point if the corresponding pods aren't running yet
    # (e.g. inference-server before the first detector loads); that's OK.
    if not args.resume:
        edge_id, inf_id = extract_image_ids(fetch_metrics(gl))
        update_image_ids(run_dir / METADATA_FILE_NAME, edge_id, inf_id)

    detectors = provision_all(gl_cloud, specs)
    wait_for_all_trained(
        gl_cloud, detectors,
        training_timeout_sec=args.training_timeout_sec,
    )

    print(f"\n=== Phase 3: measuring resources in batches of {args.batch_size} ===")
    for i in range(0, len(detectors), args.batch_size):
        batch_specs = specs[i : i + args.batch_size]
        batch_detectors = detectors[i : i + args.batch_size]
        batch_idx = i // args.batch_size + 1
        print(f"\n--- Batch {batch_idx} ({len(batch_detectors)} detector(s)) ---")
        rows = measure_batch(gl, batch_specs, batch_detectors, args.warmup_duration_sec)
        with open(results_file, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            for row in rows:
                writer.writerow(row)
                total_vram_mb = (row["total_vram_bytes"] or 0) / (1024 * 1024)
                total_ram_mb = (row["total_ram_bytes"] or 0) / (1024 * 1024)
                print(f"  {row['pipeline']} (ready={row['ready']}): VRAM={total_vram_mb:.0f} MB, RAM={total_ram_mb:.0f} MB")
        render_plot_safe(run_dir)

    print(f"\nDone! Run directory: {run_dir}")


def render_plot_safe(run_dir: Path) -> None:
    """Re-render the breakdown plot after a batch. Swallows failures so a bad plot
    (e.g. empty CSV, matplotlib backend issues on a headless box) doesn't poison
    an in-progress measurement run.
    """
    try:
        plot_ram_and_vram_usage.render(run_dir)
    except Exception as e:
        print(f"  Plot rendering failed ({type(e).__name__}: {e}). "
              f"Re-run manually with: uv run python plot_ram_and_vram_usage.py {run_dir}")


if __name__ == "__main__":
    main()
