import argparse
import secrets
import sys
import time

from groundlight import ApiException, ExperimentalApi, ModeEnum, NotFoundError
from groundlight.edge import NO_CLOUD

import groundlight_helpers as glh

# Group for all detectors created by this diagnostic script.
PRIMED_DETECTOR_GROUP_NAME = "Edge Endpoint Confidence Diagnosis"

DEFAULT_MAX_IQS = 50


def _ask_ml_edge(gl: ExperimentalApi, detector, image_bytes: bytes, **kwargs):
    """Call ask_ml on the edge endpoint. No rate limiting or retry logic; edge is not rate-limited."""
    return gl.ask_ml(detector, image_bytes, **kwargs)


def _submit_with_rate_limit_retry(gl: ExperimentalApi, detector, image_bytes: bytes, **kwargs):
    """Call submit_image_query on cloud, retrying on 429 with exponential backoff."""
    delay = 1.0
    for attempt in range(5):
        try:
            return gl.submit_image_query(detector, image_bytes, **kwargs)
        except ApiException as e:
            if e.status != 429 or attempt == 4:
                raise
            print(f'Retrying. Waiting for {delay} seconds...')
            time.sleep(delay)
            delay *= 2


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


def _format_pipelines_for_display(pipelines: list[dict]) -> str:
    """Format pipeline rows for display in error or info messages."""
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


def _select_pipeline(gl: ExperimentalApi, detector_id: str) -> dict:
    """Return the pipeline the edge endpoint uses for this detector.

    Prefers the designated edge pipeline; falls back to the active pipeline if
    no edge pipeline is set. Exits with an error if no trained pipeline is found.
    """
    try:
        pipelines = _fetch_all_detector_pipelines(gl, detector_id)
    except NotFoundError:
        print(f"Error: detector {detector_id!r} was not found.", file=sys.stderr)
        sys.exit(1)

    for p in pipelines:
        if p.get("is_edge_pipeline") and p.get("model_binary_id"):
            return p

    for p in pipelines:
        if p.get("is_active_pipeline") and p.get("model_binary_id"):
            print(
                "Warning: no trained edge pipeline found; falling back to the active pipeline.",
                file=sys.stderr,
            )
            return p

    print(
        f"Error: no trained edge or active pipeline found for detector {detector_id}.\n\n"
        f"Available pipelines:\n{_format_pipelines_for_display(pipelines)}",
        file=sys.stderr,
    )
    sys.exit(1)


def _priming_group_name(runtime_hash: str) -> str:
    """Name for a fresh PrimingGroup created during this script run."""
    return f"compare-prime:{runtime_hash}"


def _primed_detector_name(source_detector_name: str, runtime_hash: str) -> str:
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
        name=_priming_group_name(runtime_hash),
        source_ml_pipeline_id=source_ml_pipeline_id,
        detector_mode=ModeEnum.MULTI_CLASS,
        canonical_query=canonical_query,
        disable_shadow_pipelines=True,
    )


def priming_provenance_metadata(
    *,
    runtime_hash: str,
    source_detector_id: str,
    source_detector_name: str,
    source_pipeline_id: str,
    source_pipeline_config: str | None,
    source_pipeline_roles: list[str],
    source_mlb_key: str,
    priming_group_id: str,
) -> dict:
    """Structured provenance for a primed detector (stored on detector metadata)."""
    return {
        "diagnosis_script": "compare_edge_cloud_inference",
        "runtime_hash": runtime_hash,
        "source_detector_id": source_detector_id,
        "source_detector_name": source_detector_name,
        "source_pipeline_id": source_pipeline_id,
        "source_pipeline_config": source_pipeline_config,
        "source_pipeline_roles": source_pipeline_roles,
        "source_mlb_key": source_mlb_key,
        "priming_group_id": priming_group_id,
    }


def format_priming_note(
    *,
    source_detector_id: str,
    source_detector_name: str,
    source_pipeline_id: str,
    source_pipeline_config: str | None,
    source_pipeline_roles: list[str],
    source_mlb_key: str,
    priming_group_id: str,
    priming_group_name: str,
) -> str:
    """Human-readable note describing how this primed detector was created."""
    roles = "/".join(source_pipeline_roles)
    config = source_pipeline_config or "(unset)"
    return (
        "Primed detector for edge vs cloud inference diagnosis.\n"
        f"Source detector: {source_detector_id} ({source_detector_name})\n"
        f"Source pipeline: {source_pipeline_id} [{roles}] {config}\n"
        f"Source MLB: {source_mlb_key}\n"
        f"Priming group: {priming_group_id} ({priming_group_name})"
    )


def create_primed_multiclass_detector(
    gl: ExperimentalApi,
    source_detector,
    *,
    runtime_hash: str,
    priming_group_id: str,
    priming_group_name: str,
    source_pipeline_id: str,
    source_pipeline: dict,
    source_mlb_key: str,
):
    """Create a primed MULTI_CLASS detector for this run and record priming provenance."""
    pipeline_roles = _pipeline_role_tags(source_pipeline)
    metadata = priming_provenance_metadata(
        runtime_hash=runtime_hash,
        source_detector_id=source_detector.id,
        source_detector_name=source_detector.name,
        source_pipeline_id=source_pipeline_id,
        source_pipeline_config=source_pipeline.get("pipeline_config"),
        source_pipeline_roles=pipeline_roles,
        source_mlb_key=source_mlb_key,
        priming_group_id=priming_group_id,
    )
    detector = gl.create_multiclass_detector(
        name=_primed_detector_name(source_detector.name, runtime_hash),
        query=source_detector.query,
        class_names=_multiclass_class_names(source_detector),
        group_name=PRIMED_DETECTOR_GROUP_NAME,
        confidence_threshold=source_detector.confidence_threshold,
        priming_group_id=priming_group_id,
        metadata=metadata,
    )
    gl.create_note(
        detector,
        format_priming_note(
            source_detector_id=source_detector.id,
            source_detector_name=source_detector.name,
            source_pipeline_id=source_pipeline_id,
            source_pipeline_config=source_pipeline.get("pipeline_config"),
            source_pipeline_roles=pipeline_roles,
            source_mlb_key=source_mlb_key,
            priming_group_id=priming_group_id,
            priming_group_name=priming_group_name,
        ),
        is_pinned=True,
    )
    return detector


def fetch_recent_image_queries(gl_cloud: ExperimentalApi, detector_id: str, limit: int) -> list:
    """Return the most recent image queries for a detector from cloud."""
    response = gl_cloud.list_image_queries(
        detector_id=detector_id,
        page=1,
        page_size=limit,
    )
    return list(response.results or [])


def _format_label(label) -> str:
    """Format a MULTI_CLASS (or other) result label for display."""
    if label is None:
        return ""
    value = getattr(label, "value", None)
    return str(value) if value is not None else str(label)


def _format_confidence(confidence: float | None) -> str:
    if confidence is None:
        return ""
    return f"{confidence:.3f}"


def _format_created_at(dt) -> str:
    """Format a datetime as a compact UTC timestamp string."""
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def run_inference_comparison(
    gl_edge: ExperimentalApi,
    gl_cloud: ExperimentalApi,
    source_detector,
    primed_detector,
    source_image_queries: list,
) -> list[dict]:
    """
    Re-run each source image on edge (source detector via gl_edge, NO_CLOUD) and on cloud
    (primed detector via gl_cloud).

    Returns one row per source IQ with edge and cloud label/confidence.
    """
    rows: list[dict] = []
    for source_iq in source_image_queries:
        # get_image returns an open temp file (io.IOBase) written by the OpenAPI client.
        raw = gl_cloud.get_image(source_iq.id)
        image_bytes = raw.read()
        raw.close()
        if not image_bytes:
            print(f"  Skipping {source_iq.id}: no image data available.")
            continue

        # Stay well under the 3/sec cloud rate limit.
        time.sleep(0.4)

        edge_iq = _ask_ml_edge(
            gl_edge, source_detector, image_bytes, wait=0.0
        )
        glh.error_if_not_from_edge(edge_iq)

        cloud_iq = _submit_with_rate_limit_retry(
            gl_cloud,
            primed_detector,
            image_bytes,
            wait=0.0,
            human_review="NEVER",
            metadata={"diagnosis_source_image_query_id": source_iq.id},
        )
        edge_result = edge_iq.result
        cloud_result = cloud_iq.result
        rows.append(
            {
                "source_iq_id": source_iq.id,
                "source_created_at": source_iq.created_at,
                "edge_iq_id": edge_iq.id,
                "cloud_iq_id": cloud_iq.id,
                "edge_label": _format_label(edge_result.label if edge_result else None),
                "edge_confidence": edge_result.confidence if edge_result else None,
                "cloud_label": _format_label(cloud_result.label if cloud_result else None),
                "cloud_confidence": cloud_result.confidence if cloud_result else None,
            }
        )
    return rows


def print_comparison_table(rows: list[dict]) -> None:
    """Print edge vs cloud inference results in a simple fixed-width table."""
    if not rows:
        print("No inference comparison rows to display.")
        return

    headers = (
        "source_iq",
        "created_at (UTC)",
        "edge_label",
        "edge_conf",
        "cloud_label",
        "cloud_conf",
    )
    table_rows = [
        (
            row["source_iq_id"],
            _format_created_at(row["source_created_at"]),
            row["edge_label"],
            _format_confidence(row["edge_confidence"]),
            row["cloud_label"],
            _format_confidence(row["cloud_confidence"]),
        )
        for row in rows
    ]
    widths = [len(h) for h in headers]
    for table_row in table_rows:
        for i, cell in enumerate(table_row):
            widths[i] = max(widths[i], len(str(cell)))

    def fmt_row(cells: tuple[str, ...]) -> str:
        return "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(cells))

    print()
    print(fmt_row(headers))
    print(fmt_row(tuple("-" * w for w in widths)))
    for table_row in table_rows:
        print(fmt_row(table_row))


def _parse_args() -> argparse.Namespace:
    """Build the argument parser and return parsed args."""
    parser = argparse.ArgumentParser(
        description=(
            "Compare edge vs cloud inference side-by-side for a MULTI_CLASS detector.\n"
            "\n"
            "Fetches recent image queries from the source detector, re-runs each image on\n"
            "the edge endpoint (NO_CLOUD -- no cloud escalation) and on a fresh primed cloud\n"
            "detector seeded from the detector's edge pipeline MLB, then prints a comparison\n"
            "table of labels and confidence scores."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "environment variables:\n"
            "  GROUNDLIGHT_API_TOKEN   Groundlight API token (required)\n"
            "  GROUNDLIGHT_ENDPOINT    Edge endpoint URL, e.g. http://10.0.0.1:30101 (required)\n"
            "\n"
            "pipeline selection: the detector's designated edge pipeline is used automatically\n"
            "  (falls back to the active pipeline if no edge pipeline is set).\n"
            "\n"
            f"cloud resources created each run (group: '{PRIMED_DETECTOR_GROUP_NAME}'):\n"
            "  one PrimingGroup seeded from the edge pipeline MLB\n"
            "  one primed MULTI_CLASS detector\n"
            "\n"
            "safety: edge queries run in NO_CLOUD mode (no cloud escalation);\n"
            "        cloud queries use human_review=NEVER"
        ),
    )
    parser.add_argument(
        "detector_id",
        metavar="DETECTOR_ID",
        help="Groundlight detector ID (e.g. det_abc123). Must be MULTI_CLASS.",
    )
    parser.add_argument(
        "--max-iqs",
        metavar="N",
        type=int,
        default=DEFAULT_MAX_IQS,
        help=f"Maximum number of source image queries to compare (default: {DEFAULT_MAX_IQS}).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    detector_id = args.detector_id.strip()
    if not detector_id:
        print("Error: detector ID must not be empty.", file=sys.stderr)
        sys.exit(1)

    # gl_edge must use GROUNDLIGHT_ENDPOINT (edge). gl_cloud always targets cloud device-api.
    gl_edge = ExperimentalApi()
    glh.error_if_endpoint_is_cloud(gl_edge)
    gl_cloud = ExperimentalApi(endpoint=glh.CLOUD_ENDPOINT_PROD)

    pipeline = _select_pipeline(gl_cloud, detector_id)
    pipeline_id = pipeline["id"]
    mlb_key = pipeline["model_binary_id"]

    source_detector = gl_cloud.get_detector(detector_id)
    if source_detector.mode != "MULTI_CLASS":
        print(
            f"Error: source detector {detector_id} has mode {source_detector.mode!r}; "
            "only MULTI_CLASS is supported.",
            file=sys.stderr,
        )
        sys.exit(1)

    recent_queries = fetch_recent_image_queries(
        gl_cloud, detector_id, args.max_iqs
    )
    print(f"Fetched {len(recent_queries)} recent image queries from source detector {detector_id}.")

    # NO_CLOUD on edge: source-detector inference stays on the edge endpoint only (no cloud IQs).
    glh.configure_edge_endpoint(gl_edge, source_detector, edge_inference_config=NO_CLOUD)

    runtime_hash = _new_runtime_hash()

    priming_group = create_priming_group(
        gl_cloud,
        runtime_hash=runtime_hash,
        source_ml_pipeline_id=pipeline_id,
        canonical_query=source_detector.query,
    )
    primed_detector = create_primed_multiclass_detector(
        gl_cloud,
        source_detector,
        runtime_hash=runtime_hash,
        priming_group_id=priming_group.id,
        priming_group_name=priming_group.name,
        source_pipeline_id=pipeline_id,
        source_pipeline=pipeline,
        source_mlb_key=mlb_key,
    )

    print(f"Runtime hash:     {runtime_hash}")
    print(f"Source detector:  {detector_id}  ({source_detector.name})")
    print(f"Source pipeline:  {pipeline_id}  [{'/'.join(_pipeline_role_tags(pipeline))}]  {pipeline.get('pipeline_config')}")
    print(f"Source MLB:       {mlb_key}")
    print(f"Priming group:    {priming_group.id}  ({priming_group.name})")
    print(f"Primed detector:  {primed_detector.id}  ({primed_detector.name})")
    print(f"Detector group:   {PRIMED_DETECTOR_GROUP_NAME}")

    if not recent_queries:
        print("\nNo source image queries to compare.")
        return

    print(
        f"\nRe-running inference on {len(recent_queries)} image(s): "
        f"edge={source_detector.id} (NO_CLOUD), cloud={primed_detector.id} (primed)."
    )
    comparison_rows = run_inference_comparison(
        gl_edge,
        gl_cloud,
        source_detector,
        primed_detector,
        recent_queries,
    )
    print_comparison_table(comparison_rows)


if __name__ == "__main__":
    main()
