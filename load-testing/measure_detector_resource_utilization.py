"""Benchmark per-detector VRAM and RAM consumption on a running Edge Endpoint.

For each `(mode, pipeline, n, image_size)` cell in the cartesian product defined by the
YAML input, provisions a detector with the requested edge pipeline config, configures the
Edge Endpoint to run it, and records VRAM and RAM usage from /status/resources.json
into a CSV.

Usage:
    uv run python measure_detector_resource_utilization.py pipelines.yaml [--resume results.csv]

Pipelines YAML format:
    COUNT:
      n: [1, 5, 10]                # optional; defaults to mode-default singleton
      image_sizes:                 # required; list of [width, height] pairs
        - [320, 240]
        - [640, 480]
      pipelines:
        - count-step-yolox
        - count-step-centernet
    BINARY:
      # `n` is not accepted for BINARY (always 2). Bare list of names is shorthand
      # for `pipelines:` and requires the script-level image_sizes to be set elsewhere.
      - generic-cached-timm-efficientnetv2s-calibrated-mlp
"""

import argparse
import csv
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml
from groundlight import Detector, ExperimentalApi

import groundlight_helpers as glh

import time

NAME_PREFIX: str = "edge-bench"
GROUP_NAME: str = "Edge Benchmarking"
RESULTS_DIR: Path = Path(__file__).parent / "benchmark_results"
CSV_FIELDS: list[str] = [
    "mode", "n", "pipeline", "image_width", "image_height", "detector_id", "ready",
    "primary_vram_bytes", "oodd_vram_bytes", "total_vram_bytes",
    "primary_ram_bytes", "oodd_ram_bytes", "total_ram_bytes",
    "system_vram_used_bytes", "system_vram_total_bytes",
    "system_ram_used_bytes", "system_ram_total_bytes",
]


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
        if mode not in glh.SUPPORTED_DETECTOR_MODES:
            raise ValueError(f"Unsupported detector mode: {mode}. Supported: {sorted(glh.SUPPORTED_DETECTOR_MODES)}")

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


def detector_resource_row(resources: dict, detector_id: str) -> Optional[dict]:
    """Return the per-detector entry from /status/resources.json, or None if not present."""
    for det in resources.get("detectors") or []:
        if det.get("detector_id") == detector_id:
            return det
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pipelines", type=Path, help="Path to YAML file listing pipelines to benchmark.")
    parser.add_argument("--resume", type=Path, default=None, help="Path to an existing results CSV; already-recorded rows are skipped.")
    parser.add_argument("--batch-size", type=int, default=1, help="Detectors configured on the edge endpoint per measurement batch.")
    parser.add_argument("--training-timeout-sec", type=float, default=60 * 20, help="Per-detector training timeout. Cloud trains concurrently, so total wall-time is bounded by the slowest single detector.")
    return parser.parse_args()


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
) -> list[dict]:
    """Configure the Edge Endpoint with this batch, sample resources, and return CSV rows."""
    try:
        glh.configure_edge_endpoint(gl, batch_detectors)
    except TimeoutError:
        print("  Timed out waiting for readiness; recording with ready=False.")

    # We should be ready here right away, but in practice I am finding that we aren't
    # always. We'll retry a bit to ensure readiness. 
    for n in range(10):
        readiness = gl.edge.get_detector_readiness().get(detector.id, False)
        if readiness:
            break
        print(f'Not ready after {n} iterations')
        time.sleep(1)

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
            "ready": readiness,
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
    args = parse_args()

    all_specs = load_detector_specs(args.pipelines)
    print(f"Loaded {len(all_specs)} detector spec(s) from {args.pipelines}:")

    if args.resume:
        completed = load_completed(args.resume)
        results_file: Path = args.resume
        print(f"Resuming from {results_file} ({len(completed)} pipeline(s) already recorded)")
        specs = [s for s in all_specs if spec_key(s) not in completed]
        print(f"{len(specs)} pipeline(s) remaining")
    else:
        RESULTS_DIR.mkdir(exist_ok=True)
        run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_file = RESULTS_DIR / f"resource_benchmark_{run_timestamp}.csv"
        with open(results_file, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=CSV_FIELDS).writeheader()
        print(f"Created new results file: {results_file}")
        specs = all_specs

    if not specs:
        print("Nothing to do.")
        return

    gl = ExperimentalApi()
    glh.error_if_endpoint_is_cloud(gl)
    gl_cloud = ExperimentalApi(endpoint=glh.CLOUD_ENDPOINT_PROD)

    detectors = provision_all(gl_cloud, specs)
    wait_for_all_trained(
        gl_cloud, detectors,
        training_timeout_sec=args.training_timeout_sec,
    )

    print(f"\n=== Phase 3: measuring resources in batches of {args.batch_size} ===")
    for i in range(0, len(detectors), args.batch_size):
        batch_specs = specs[i : i + args.batch_size]
        batch_detectors = detectors[i : i + args.batch_size]
        print(f"\n--- Batch {i // args.batch_size + 1} ({len(batch_detectors)} detector(s)) ---")
        rows = measure_batch(gl, batch_specs, batch_detectors)
        with open(results_file, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            for row in rows:
                writer.writerow(row)
                total_vram_mb = (row["total_vram_bytes"] or 0) / (1024 * 1024)
                total_ram_mb = (row["total_ram_bytes"] or 0) / (1024 * 1024)
                print(f"  {row['pipeline']} (ready={row['ready']}): VRAM={total_vram_mb:.0f} MB, RAM={total_ram_mb:.0f} MB")

    print(f"\nDone! Results saved to {results_file}")


if __name__ == "__main__":
    main()
