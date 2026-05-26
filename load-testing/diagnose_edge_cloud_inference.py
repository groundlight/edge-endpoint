"""
Diagnose edge vs cloud inference discrepancies for an existing detector.

Each run creates a fresh PrimingGroup (seeded from a chosen MLPipeline MLB) and a fresh
MULTI_CLASS primed detector in a dedicated group. MULTI_CLASS source detectors only.

Requires GROUNDLIGHT_API_TOKEN.

Example:
    uv run python diagnose_edge_cloud_inference.py det_abc123 \\
        --pipeline-id mlpipe_abc123
"""

import argparse
import secrets
import sys

from groundlight import ExperimentalApi, ModeEnum, NotFoundError

# Group for all detectors created by this diagnostic script.
PRIMED_DETECTOR_GROUP_NAME = "Edge Cloud Inference Diagnosis"


def _new_runtime_hash() -> str:
    """Return a short unique id for this script invocation."""
    return secrets.token_hex(6)


def _fetch_all_detector_pipelines(gl: ExperimentalApi, detector_id: str) -> list[dict]:
    """Return every MLPipeline row for a detector from the cloud pipelines API."""
    pipelines: list[dict] = []
    page = 1
    page_size = 50
    while True:
        response = gl.list_detector_pipelines(detector_id, page=page, page_size=page_size)
        pipelines.extend(p.model_dump() for p in response.results)
        if response.next is None:
            break
        page += 1
    return pipelines


def _pipeline_role_tags(pipeline: dict) -> list[str]:
    """Short labels describing how this pipeline is used on the detector."""
    if pipeline.get("is_active_pipeline"):
        return ["active"]
    if pipeline.get("is_edge_pipeline"):
        return ["edge"]
    if pipeline.get("is_oodd_pipeline"):
        return ["oodd"]
    if pipeline.get("is_unclear_pipeline"):
        return ["unclear"]
    pipeline_type = pipeline.get("type")
    if pipeline_type:
        return [pipeline_type]
    return ["shadow"]


def _format_pipelines_for_error(pipelines: list[dict]) -> str:
    """Format pipeline rows for the missing --pipeline-id error message."""
    if not pipelines:
        return "  (no pipelines found for this detector)"

    lines: list[str] = []
    for pipeline in sorted(pipelines, key=lambda p: p.get("pipeline_config") or ""):
        role = "/".join(_pipeline_role_tags(pipeline))
        config = pipeline.get("pipeline_config") or "(unset)"
        trained = "trained" if pipeline.get("trained_at") else "untrained"
        mlb = pipeline.get("model_binary_id") or "no MLB"
        lines.append(f"  {pipeline.get('id')}  [{role}]  {config}  ({trained}, {mlb})")
    return "\n".join(lines)


def _exit_missing_pipeline_id(gl: ExperimentalApi, detector_id: str) -> None:
    """Print available pipeline IDs for the detector and exit."""
    try:
        pipelines = _fetch_all_detector_pipelines(gl, detector_id)
    except NotFoundError:
        print(f"Error: detector {detector_id!r} was not found.", file=sys.stderr)
        sys.exit(1)

    print(
        "Error: --pipeline-id is required.\n\n"
        f"Available pipelines for detector {detector_id}:\n"
        f"{_format_pipelines_for_error(pipelines)}\n\n"
        "Pass one of the pipeline IDs above with --pipeline-id.",
        file=sys.stderr,
    )
    sys.exit(2)


def _find_pipeline(pipelines: list[dict], pipeline_id: str) -> dict:
    """Return the pipeline dict matching pipeline_id, or raise if not found."""
    for p in pipelines:
        if p.get("id") == pipeline_id:
            return p
    raise ValueError(
        f"Pipeline {pipeline_id!r} not found on this detector. "
        "Run without --pipeline-id to see available pipelines."
    )


def priming_group_name(runtime_hash: str) -> str:
    """Name for a fresh PrimingGroup created during this script run."""
    return f"diagnose-prime:{runtime_hash}"


def primed_detector_name(source_detector_name: str, runtime_hash: str) -> str:
    """Name for a fresh primed detector created during this script run."""
    suffix = f" [primed:{runtime_hash}]"
    max_base_len = 200 - len(suffix)
    base = source_detector_name[:max_base_len]
    return f"{base}{suffix}"


def _multiclass_class_names(source_detector) -> list[str]:
    """Extract class names from a MULTI_CLASS detector."""
    mode_config = source_detector.mode_configuration or {}
    class_names = mode_config.get("class_names")
    if not class_names:
        raise ValueError(
            f"Source detector {source_detector.id} is MULTI_CLASS but has no class_names in mode_configuration."
        )
    return list(class_names)


def create_priming_group(
    gl: ExperimentalApi,
    *,
    runtime_hash: str,
    source_ml_pipeline_id: str,
    canonical_query: str,
):
    """Create a PrimingGroup seeded from the given pipeline for this run."""
    # disable_shadow_pipelines=True: keep the primed active MLB from being replaced by
    # default shadow pipelines or post-evaluation active-pipeline switching during diagnosis.
    return gl.create_priming_group(
        name=priming_group_name(runtime_hash),
        source_ml_pipeline_id=source_ml_pipeline_id,
        detector_mode=ModeEnum.MULTI_CLASS,
        canonical_query=canonical_query,
        disable_shadow_pipelines=True,
    )


def create_primed_multiclass_detector(
    gl: ExperimentalApi,
    source_detector,
    *,
    runtime_hash: str,
    priming_group_id: str,
):
    """Create a primed MULTI_CLASS detector for this run."""
    return gl.create_multiclass_detector(
        name=primed_detector_name(source_detector.name, runtime_hash),
        query=source_detector.query,
        class_names=_multiclass_class_names(source_detector),
        group_name=PRIMED_DETECTOR_GROUP_NAME,
        confidence_threshold=source_detector.confidence_threshold,
        priming_group_id=priming_group_id,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnose why an Edge Endpoint returns lower-confidence or different answers "
            "than Groundlight cloud for the same detector."
        ),
    )
    parser.add_argument(
        "detector_id",
        metavar="DETECTOR_ID",
        help="Groundlight detector ID (e.g. det_abc123).",
    )
    parser.add_argument(
        "--pipeline-id",
        metavar="PIPELINE_ID",
        help="MLPipeline ID to prime from (e.g. mlpipe_abc123).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    detector_id = args.detector_id.strip()
    if not detector_id:
        print("Error: detector ID must not be empty.", file=sys.stderr)
        sys.exit(1)

    gl = ExperimentalApi()

    if not args.pipeline_id:
        _exit_missing_pipeline_id(gl, detector_id)

    pipeline_id = args.pipeline_id.strip()
    pipelines = _fetch_all_detector_pipelines(gl, detector_id)
    pipeline = _find_pipeline(pipelines, pipeline_id)

    mlb_key = pipeline.get("model_binary_id")
    if not mlb_key:
        print(
            f"Error: pipeline {pipeline_id!r} has no trained MLBinary yet. "
            "Wait for training to complete before using it as a priming source.",
            file=sys.stderr,
        )
        sys.exit(1)

    source_detector = gl.get_detector(detector_id)
    if source_detector.mode != "MULTI_CLASS":
        print(
            f"Error: source detector {detector_id} has mode {source_detector.mode!r}; "
            "only MULTI_CLASS is supported.",
            file=sys.stderr,
        )
        sys.exit(1)

    runtime_hash = _new_runtime_hash()

    priming_group = create_priming_group(
        gl,
        runtime_hash=runtime_hash,
        source_ml_pipeline_id=pipeline_id,
        canonical_query=source_detector.query,
    )
    primed_detector = create_primed_multiclass_detector(
        gl,
        source_detector,
        runtime_hash=runtime_hash,
        priming_group_id=priming_group.id,
    )

    print(f"Runtime hash:     {runtime_hash}")
    print(f"Source detector:  {detector_id}  ({source_detector.name})")
    print(f"Source pipeline:  {pipeline_id}  [{'/'.join(_pipeline_role_tags(pipeline))}]  {pipeline.get('pipeline_config')}")
    print(f"Source MLB:       {mlb_key}")
    print(f"Priming group:    {priming_group.id}  ({priming_group.name})")
    print(f"Primed detector:  {primed_detector.id}  ({primed_detector.name})")
    print(f"Detector group:   {PRIMED_DETECTOR_GROUP_NAME}")


if __name__ == "__main__":
    main()
