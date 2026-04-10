import argparse
import csv
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import yaml
import requests
from groundlight import ExperimentalApi
from groundlight.edge import EdgeEndpointConfig, GlobalConfig, NO_CLOUD
from model import Detector

DETECTOR_BATCH_SIZE: int = 2
NAME_PREFIX: str = "vram-bench"
GROUP_NAME: str = "Edge Benchmarking"
QUERY: str = "benchmark detector for VRAM measurement"
EDGE_ENDPOINT_URL: str = "http://localhost:30101"
RESULTS_DIR: Path = Path(__file__).parent / "results"
CSV_FIELDS: List[str] = ["mode", "pipeline", "detector_id", "ready", "primary_vram_bytes", "oodd_vram_bytes", "total_vram_bytes"]


def load_pipelines(path: Path) -> List[Tuple[str, str]]:
    """Load (mode, pipeline) pairs from a YAML file.

    Expected format:
        BINARY:
          - generic-cached-timm-efficientnetv2s-calibrated-mlp
          - basic-active-learning-pipeline
        MULTI_CLASS:
          - multiclass-generic-cached-timm-efficientnetv2s-calibrated-mlp
        COUNT:
          - count-step-centernet
        BOUNDING_BOX:
          - bounding-boxes-step-yolox
    """
    with open(path) as f:
        data = yaml.safe_load(f)
    pipelines: List[Tuple[str, str]] = []
    for mode, names in data.items():
        for name in names or []:
            pipelines.append((mode, name))
    return pipelines


def load_completed(path: Path) -> Set[Tuple[str, str]]:
    """Read an existing results CSV and return the set of (mode, pipeline) pairs already recorded."""
    completed: Set[Tuple[str, str]] = set()
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            completed.add((row["mode"], row["pipeline"]))
    return completed


def short_hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:8]


def _create_new_detector(gl: ExperimentalApi, mode: str, edge_pipeline_config: str, name: str) -> Detector:
    common: Dict[str, object] = dict(
        name=name, query=QUERY, group_name=GROUP_NAME,
        edge_pipeline_config=edge_pipeline_config,
    )
    if mode in ("BINARY", "OODD"):
        return gl.create_detector(**common)
    elif mode == "MULTI_CLASS":
        return gl.create_multiclass_detector(class_names=["a", "b", "c"], **common)
    elif mode == "COUNT":
        return gl.create_counting_detector(class_name="object", **common)
    elif mode == "BOUNDING_BOX":
        return gl.create_bounding_box_detector(class_name="object", **common)
    else:
        raise ValueError(f"Unknown mode: {mode}")


def get_or_create_detector(gl: ExperimentalApi, mode: str, pipeline: str) -> Detector:
    name: str = f"{NAME_PREFIX}-{mode}-{short_hash(pipeline)}"
    try:
        detector = gl.get_detector_by_name(name)
        print(f"    Found existing detector {detector.id}")
        return detector
    except Exception:
        detector = _create_new_detector(gl, mode, pipeline, name)
        print(f"    Created detector {detector.id}")
        return detector


def fetch_gpu_metrics() -> Dict:
    resp = requests.get(f"{EDGE_ENDPOINT_URL}/status/gpu.json", timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_detector_vram(gpu_data: Dict, detector_id: str) -> Optional[Dict[str, int]]:
    for det in gpu_data.get("detectors", []):
        if det["detector_id"] == detector_id:
            return det
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark VRAM usage of edge detector pipelines.")
    parser.add_argument(
        "pipelines",
        type=Path,
        help="Path to YAML file listing pipelines to benchmark (see docstring in load_pipelines for format).",
    )
    parser.add_argument(
        "--resume",
        type=Path,
        default=None,
        help="Path to an existing results CSV to resume from. Already-recorded pipelines will be skipped.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    all_pipelines: List[Tuple[str, str]] = load_pipelines(args.pipelines)
    print(f"Loaded {len(all_pipelines)} pipeline(s) from {args.pipelines}")

    if args.resume:
        completed: Set[Tuple[str, str]] = load_completed(args.resume)
        results_file: Path = args.resume
        print(f"Resuming from {results_file} ({len(completed)} pipeline(s) already recorded)")
        pipelines = [p for p in all_pipelines if p not in completed]
        print(f"{len(pipelines)} pipeline(s) remaining")
    else:
        RESULTS_DIR.mkdir(exist_ok=True)
        run_timestamp: str = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_file = RESULTS_DIR / f"vram_benchmark_{run_timestamp}.csv"
        with open(results_file, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=CSV_FIELDS).writeheader()
        print(f"Created new results file: {results_file}")
        pipelines = all_pipelines

    if not pipelines:
        print("Nothing to do.")
        return

    gl: ExperimentalApi = ExperimentalApi()

    for i in range(0, len(pipelines), DETECTOR_BATCH_SIZE):
        batch: List[Tuple[str, str]] = pipelines[i : i + DETECTOR_BATCH_SIZE]
        batch_num: int = i // DETECTOR_BATCH_SIZE + 1
        print(f"\n--- Batch {batch_num} ---")

        detectors: List[Detector] = []
        batch_modes: List[str] = []
        batch_pipelines: List[str] = []
        for mode, pipeline in batch:
            print(f"  {mode}: {pipeline}")
            detector: Detector = get_or_create_detector(gl, mode, pipeline)
            detectors.append(detector)
            batch_modes.append(mode)
            batch_pipelines.append(pipeline)

        global_config: GlobalConfig = GlobalConfig(refresh_rate=1.0)
        edge_endpoint_config: EdgeEndpointConfig = EdgeEndpointConfig(global_config=global_config)

        for d in detectors:
            edge_endpoint_config.add_detector(d, NO_CLOUD)

        print("  Configuring the edge...")
        try:
            gl.edge.set_config(edge_endpoint_config)
            print("  All detectors ready!")
        except TimeoutError:
            print("  Timed out waiting for readiness (models may be untrained). Continuing with partial results.")

        detector_readiness: Dict[str, bool] = gl.edge.get_detector_readiness()

        gpu_data: Dict = fetch_gpu_metrics()

        with open(results_file, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            for mode, pipeline, detector in zip(batch_modes, batch_pipelines, detectors):
                ready: bool = detector_readiness.get(detector.id, False)
                vram = get_detector_vram(gpu_data, detector.id)
                row: Dict = {
                    "mode": mode,
                    "pipeline": pipeline,
                    "detector_id": detector.id,
                    "ready": ready,
                    "primary_vram_bytes": vram["primary_vram_bytes"] if vram else None,
                    "oodd_vram_bytes": vram["oodd_vram_bytes"] if vram else None,
                    "total_vram_bytes": vram["total_vram_bytes"] if vram else None,
                }
                writer.writerow(row)
                if vram:
                    total_mb: float = vram["total_vram_bytes"] / (1024 * 1024)
                    print(f"  {pipeline} (ready={ready}): {total_mb:.0f} MB")
                else:
                    print(f"  {pipeline} (ready={ready}): no VRAM data")

    print(f"\nDone! Results saved to {results_file}")


if __name__ == "__main__":
    main()
