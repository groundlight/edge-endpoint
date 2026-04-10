import csv
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from groundlight import ExperimentalApi
from groundlight.edge import EdgeEndpointConfig, GlobalConfig, NO_CLOUD
from model import Detector


# All pipeline configs defined in zuuul's predictors/pipeline/registry, grouped by detector mode.
# Excludes: symlinks (duplicates), constant/mock pipelines, and cloud-only LLM pipelines.
# Generated from zuuul/predictors/predictors/pipeline/registry/ and predictors_edge/pipeline/registry/.
PIPELINES: List[Tuple[str, str]] = [
    # --- BINARY (default edge: generic-cached-timm-efficientnetv2s-calibrated-mlp) ---
    ("BINARY", "generic-cached-timm-efficientnetv2s-calibrated-mlp"),
    # ("BINARY", "groundlight-default-edge"),
    ("BINARY", "basic-active-learning-mcdropout-pipeline"),
    ("BINARY", "basic-active-learning-pipeline"),
    ("BINARY", "generic-cached-timm-tinynet_e-mlp"),
    ("BINARY", "groundlight-decision-region-default-2025-01-08"),
    ("BINARY", "groundlight-default-2025-01-08"),
    ("BINARY", "groundlight-gru-temporal"),
    ("BINARY", "groundlight-mlp-temporal"),
    ("BINARY", "zero-shot-object-groundingdino-decision-region"),
    ("BINARY", "generic-cached-b4mu11-add-smooth-mlp"),
    ("BINARY", "generic-cached-timm-mobilenetv3_small_050-calibrated-smoothed-mlp"),
    ("BINARY", "generic-cached-timm-resnet18-knn"),
    ("BINARY", "e2e-efficientnet-b0-3epochs"),
    ("BINARY", "crop-to-roi-alkishop-lock-2"),
    ("BINARY", "crop-to-roi-green-dumpster-overflow"),
    ("BINARY", "roi-door-locked"),
    ("BINARY", "overhead-person-count"),
    ("BINARY", "zero-shot-groundingdino-object"),
    ("BINARY", "zero-shot-text-knn-mlp-pipeline"),
    ("BINARY", "e2e-efficientnet-b0-3epochs-with-calibration"),
    ("BINARY", "generic-cached-timm-efficientnetv2s-knn"),
    ("BINARY", "generic-cached-timm-squash-eva02_large_mim-calibrated-smoothed-mlp"),
    ("BINARY", "generic-cached-timm-squash-vit_reg4_dinov2-calibrated-smoothed-mlp"),
    ("BINARY", "generic-cached-timm-squash-vit_so400_siglipv2-calibrated-smoothed-mlp"),
    ("BINARY", "generic-cached-timm-squash-vitamin_xl-calibrated-smoothed-mlp"),
    # # prod/custom
    # ("BINARY", "timm-border-groundlight-default-2024-11-13"),
    # ("BINARY", "timm-squash-groundlight-default-2024-11-08"),
    # ("BINARY", "zero-shot-switching-3scale-efficientnetv2s-oodd-calibrated-mlp"),
    # ("BINARY", "zero-shot-text-knn-mlp-oodd"),
    # ("BINARY", "zero-shot-switching-timm-efficientnetv2s-oodd-nw"),
    # # experimental
    # ("BINARY", "e2e-efficientnet-b2-3epochs-with-calibration"),
    # ("BINARY", "e2e-efficientnet-b4-3epochs-with-calibration"),
    # ("BINARY", "e2e-timm-efficientnetv2_s-3epochs-with-calibration"),
    # ("BINARY", "generic-efficientnet-pipeline"),
    # ("BINARY", "numpy-padding-calibrated-e2e-100epochs-reset"),
    # ("BINARY", "numpy-padding-e2e-100epochs-reset"),
    # ("BINARY", "resize-both-sides-calibrated-e2e-100epochs-reset"),
    # ("BINARY", "resize-both-sides-e2e-100epochs-reset"),
    # ("BINARY", "zero-shot-switching-calibrated-e2e-efficientnet-b0-100epochs-reset-on-train"),
    # ("BINARY", "zero-shot-switching-e2e-efficientnet-b0-100epochs-reset-on-train"),
    # ("BINARY", "zero-shot-switching-with-pure-efficientnet-b0--chainlink-fence-wide-angle--no-reset-on-train--cropped"),
    # ("BINARY", "zero-shot-switching-with-pure-efficientnet-b0--chainlink-fence-wide-angle--no-reset-on-train"),
    # ("BINARY", "zero-shot-switching-with-pure-efficientnet-b0--chainlink-fence-wide-angle--reset-on-train--cropped"),
    # ("BINARY", "zero-shot-switching-with-pure-efficientnet-b0--chainlink-fence-wide-angle--reset-on-train"),
    # ("BINARY", "ensemble-convnext-eva-mlp"),
    # ("BINARY", "ensemble-efficientnet-clip"),
    # ("BINARY", "crop-to-roi-chainlink-fence-fixed"),
    # ("BINARY", "generic-cached-b4mu11-add-smooth-knn-mlp"),
    # ("BINARY", "generic-cached-b4mu11-mlp"),
    # ("BINARY", "generic-cached-efficientnet-knn"),
    # ("BINARY", "generic-cached-efficientnet-xgb"),
    # ("BINARY", "generic-cached-distance-based-outlier-detector"),
    # ("BINARY", "generic-cached-timm-convnext_xxl-mlp"),
    # ("BINARY", "generic-cached-timm-efficientnetv2s-calibrated-autoflaml"),
    # ("BINARY", "generic-cached-timm-efficientnetv2s-xgb"),
    # ("BINARY", "generic-cached-timm-eva02_large_clip-mlp"),
    # ("BINARY", "generic-cached-timm-eva02_large_mlm-mlp"),
    # ("BINARY", "generic-cached-timm-squash-convnextv2_tiny-calibrated-smoothed-mlp"),
    # ("BINARY", "generic-cached-timm-squash-eva02_giant_clip-calibrated-smoothed-mlp"),
    # ("BINARY", "generic-cached-timm-squash-vit_base_clip-calibrated-smoothed-mlp"),
    # ("BINARY", "generic-cached-timm-squash-vit_giantopt_siglipv2-calibrated-smoothed-mlp"),
    # ("BINARY", "generic-cached-timm-squash-vit_huge_clip-calibrated-smoothed-mlp"),
    # ("BINARY", "generic-cached-timm-mobilenetv3_small-calibrated-smoothed-mlp"),
    # ("BINARY", "generic-cached-timm-mobilenetv3_small_075-calibrated-smoothed-mlp"),
    # ("BINARY", "experimental-lora-beit-large-patch16-224"),
    # ("BINARY", "mahalanobis-oodd"),
    # ("BINARY", "numpy-padding-default-2023-11-13"),
    # ("BINARY", "numpy-padding-transform-constant-0"),
    # ("BINARY", "zero-shot-switching-efficientnetv2s-oodd-calibrated--chainlink-fence-wide-angle--cropped"),
    # ("BINARY", "zero-shot-text-knn-mcdropout-oodd"),
    # ("BINARY", "zero-shot-text-knn-mlp-oodd-calibrated"),
    # # experimental objdet-based binary
    # ("BINARY", "at-least-2-pastries-centernet"),
    # ("BINARY", "at-least-2-pastries-groundingdino"),
    # ("BINARY", "at-least-2-pastries-yolos"),
    # ("BINARY", "at-least-2-pastries-yolox"),
    # ("BINARY", "at-least-2-pastries"),
    # ("BINARY", "at-least-one-customer-rcnn-crop-classify"),
    # ("BINARY", "at-least-one-customer-rcnn-only"),
    # ("BINARY", "at-least-one-customer-rcnn-pretrained-v2"),
    # ("BINARY", "faster_rcnn_training_config_example"),
    # ("BINARY", "lowpri-hatbander-bandlength"),
    # ("BINARY", "more-than-two-customers"),
    # ("BINARY", "tag-present"),
    # # deprecated
    # ("BINARY", "groundlight-decision-region-default-2023-11-13"),
    # ("BINARY", "groundlight-decision-region-default-2024-11-14"),
    # ("BINARY", "groundlight-default-2023-11-13"),
    # ("BINARY", "groundlight-default-2024-11-14"),
    # ("BINARY", "groundlight-oodd-default"),
    # ("BINARY", "zero-shot-switching-efficientnetv2s-oodd"),
    # # --- MULTI_CLASS (default edge: multiclass-generic-cached-timm-efficientnetv2s-calibrated-mlp) ---
    # ("MULTI_CLASS", "multiclass-generic-cached-timm-efficientnetv2s-calibrated-mlp"),
    # ("MULTI_CLASS", "groundlight-default-multiclass-2025-01-08"),
    # ("MULTI_CLASS", "multiclass-generic-cached-timm-squash-effnetv2-calibrated-smoothed-mlp"),
    # ("MULTI_CLASS", "multiclass-generic-cached-timm-squash-eva02_large_mim-calibrated-smoothed-mlp"),
    # ("MULTI_CLASS", "multiclass-generic-cached-timm-squash-vit_reg4_dinov2-calibrated-smoothed-mlp"),
    # ("MULTI_CLASS", "multiclass-generic-cached-timm-squash-vit_so400_siglipv2-calibrated-smoothed-mlp"),
    # ("MULTI_CLASS", "multiclass-generic-cached-timm-squash-vitamin_xl-calibrated-smoothed-mlp"),
    # ("MULTI_CLASS", "e2e-timm-efficientnetv2_s-3epochs-with-multiclass-calibration"),
    # ("MULTI_CLASS", "generic-cached-timm-efficientnetv2s-mlp-multiclass"),
    # ("MULTI_CLASS", "generic-cached-timm-mobilenetv3_small-calibrated-smoothed-mlp-multiclass"),
    # ("MULTI_CLASS", "multiclass-generic-cached-timm-squash-vit_base_dinov3-calibrated-smoothed-mlp"),
    # ("MULTI_CLASS", "multiclass-generic-cached-timm-squash-vit_large_dinov3-calibrated-smoothed-mlp"),
    # ("MULTI_CLASS", "groundlight-default-multiclass-2024-11-20"),
    # # --- COUNT (default edge: count-step-centernet) ---
    # ("COUNT", "count-step-centernet"),
    # ("COUNT", "count-step-groundingdino"),
    # ("COUNT", "count-step-rfdetr"),
    # ("COUNT", "count-step-yolox"),
    # ("COUNT", "count-step-yolox-tracking"),
    # ("COUNT", "count-step-yolos"),
    # ("COUNT", "count-step-yolov9"),
    # ("COUNT", "count-step-groundingdino-no-timm-selector"),
    # # --- BOUNDING_BOX (default edge: bounding-boxes-step-yolox) ---
    # ("BOUNDING_BOX", "bounding-boxes-step-yolox"),
    # ("BOUNDING_BOX", "bounding-boxes-step-centernet"),
    # ("BOUNDING_BOX", "bounding-boxes-step-groundingdino"),
    # ("BOUNDING_BOX", "bounding-boxes-step-rfdetr"),
    # ("BOUNDING_BOX", "zero-shot-rfdetr-object"),
    # # --- OODD (shared across modes, deployed as second inference pod) ---
    # ("OODD", "groundlight-oodd-default-2025-02-25"),
]

DETECTOR_BATCH_SIZE: int = 3
NAME_PREFIX: str = "vram-bench"
GROUP_NAME: str = "Edge Benchmarking"
QUERY: str = "benchmark detector for VRAM measurement"
EDGE_ENDPOINT_URL: str = "http://localhost:30101"
RESULTS_DIR: Path = Path(__file__).parent / "results"

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



gl: ExperimentalApi = ExperimentalApi()

RESULTS_DIR.mkdir(exist_ok=True)
run_timestamp: str = datetime.now().strftime("%Y%m%d_%H%M%S")
results_file: Path = RESULTS_DIR / f"vram_benchmark_{run_timestamp}.csv"
CSV_FIELDS: List[str] = ["mode", "pipeline", "detector_id", "ready", "primary_vram_bytes", "oodd_vram_bytes", "total_vram_bytes"]

with open(results_file, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
    writer.writeheader()

print(f"Results will be written to {results_file}")

for i in range(0, len(PIPELINES), DETECTOR_BATCH_SIZE):
    batch: List[Tuple[str, str]] = PIPELINES[i : i + DETECTOR_BATCH_SIZE]
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