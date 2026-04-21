from groundlight import ExperimentalApi, Detector, ApiException, ImageQuery
from groundlight.edge import EdgeEndpointConfig, InferenceConfig, NO_CLOUD

from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
import requests
import json
import time
import yaml
from tqdm import trange

import image_helpers as imgh
from urllib.parse import urlparse

CLOUD_ENDPOINT_PROD = 'https://api.groundlight.ai/device-api'
SUPPORTED_DETECTOR_MODES = {"BINARY", "COUNT", "BOUNDING_BOX", "MULTI_CLASS"}

# Image query submission args that will ensure a query is never escalated to the cloud, 
# unless an inference pod doesn't exist for the detector, in which case we have no choice but to escalate
IQ_KWARGS_FOR_NO_ESCALATION = {'wait': 0.0, 'human_review': 'NEVER', 'confidence_threshold': 0.0}
IQ_KWARGS_NON_HUMAN_CLOUD_ESCALATION = {'wait': 0.0, 'human_review': 'NEVER', 'confidence_threshold': 1.0}
PRIMING_MAX_BATCH_SIZE = 10


def hash_pipeline_config(pipeline_config: str) -> str:
    """Return a short deterministic hash of the pipeline config string."""
    return hashlib.sha256(pipeline_config.encode()).hexdigest()[:12]


def normalize_edge_pipeline_config(pipeline_config: str | None) -> str | None:
    """Trim surrounding whitespace and normalize empty values to None."""
    if pipeline_config is None:
        return None
    normalized = pipeline_config.strip()
    return normalized or None


def _pipeline_configs_equal(a: str | None, b: str | None) -> bool:
    """Return True if the two pipeline config strings are equivalent (YAML-normalized)."""
    return yaml.safe_load(a or "") == yaml.safe_load(b or "")


class APIError(Exception):
    """Any response from the Groundlight API that is not 200
    """
    pass

def call_api(url: str, params: dict) -> dict:
    """Perform a GET request with API token and return decoded JSON or raise APIError."""

    headers = {
        "X-API-Token": os.environ.get('GROUNDLIGHT_API_TOKEN')
    }
    
    response = requests.get(url, params=params, headers=headers)
    if response.status_code == 200:
        response_content = response.content.decode('utf-8')
        return json.loads(response_content)
    else:
        raise APIError(
            f"Request failed with status code {response.status_code} | "
            f"Response content: {response.content}" 
            )

def get_detector_pipelines(gl: ExperimentalApi, detector_id: str) -> list[dict]:
    """Return all MLPipeline records for a detector via the pipelines endpoint."""
    url = gl.endpoint + f"/v1/detectors/{detector_id}/pipelines"
    data = call_api(url, {})
    return data.get("results", [])


def get_edge_pipeline_details(gl: ExperimentalApi, detector_id: str) -> dict:
    """Return training status for the edge pipeline.

    Returns {"trained_at": str | None, "label_cnt": int | None, "pipeline_config": str | None}.
    If no edge pipeline exists, all values are None.
    """
    pipelines = get_detector_pipelines(gl, detector_id)
    for p in pipelines:
        if p.get("is_edge_pipeline"):
            metrics = p.get("metrics") or {}
            return {
                "trained_at": p.get("trained_at"),
                "label_cnt": metrics.get("label_cnt"),
                "pipeline_config": p.get("pipeline_config"),
            }
    return {"trained_at": None, "label_cnt": None, "pipeline_config": None}

def call_edge_api(gl_client: ExperimentalApi, path: str, params: dict) -> dict:
    """Perform a GET request against the Edge Endpoint's edge-api and return decoded JSON."""
    url = gl_client.endpoint.replace('/device-api', '/edge-api') + path

    return call_api(url, params)

def get_detector_edge_pipeline_configs(gl: ExperimentalApi, detector_id: str) -> dict:
    """
    Get the detector's configured edge pipeline configs from cloud metadata.

    These have not necessarily been downloaded to this Edge Endpoint yet.
    They represent the desired edge pipeline configs known in the cloud.
    """
    
    # Ideally we would use `gl.edge_api.get_model_urls` to get this info, but
    # currently it raises an exception on new detectors (detectors that haven't trained), which makes it unusable for this script.
    # model_urls = gl.edge_api.get_model_urls(detector_id)

    path = f'/v1/fetch-model-urls/{detector_id}/'
    params = {}
    
    decoded_response = call_edge_api(gl, path, params)

    return {
        "pipeline_config": decoded_response.get('pipeline_config'),
        "oodd_pipeline_config": decoded_response.get('oodd_pipeline_config'),
    }

def get_detector_edge_metrics(gl: ExperimentalApi, detector_id: str) -> dict | None:
    """Fetch edge status metrics and return details for a detector currently running on edge."""

    metrics = _get_status_metrics(gl)
    raw = metrics.get('detector_details')
    if not raw:
        return None
    detector_details = json.loads(raw)
    return detector_details.get(detector_id)

def _get_status_metrics(gl: ExperimentalApi) -> dict:
    """Retrieve the consolidated edge status metrics JSON from the Edge Endpoint's /status/metrics.json."""
    base = gl.endpoint.replace('/device-api', '')
    url = base + '/status/metrics.json'
    return call_api(url, {})

def get_container_images_map(gl: ExperimentalApi) -> dict[str, dict[str, str]]:
    """Return a map of pod -> {container: image_id} from edge status metrics."""
    metrics = _get_status_metrics(gl)
    k3s_stats = metrics.get('k3s_stats', {}) or {}
    raw = k3s_stats.get('container_images', {})
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return raw

def get_edge_and_inference_images(gl: ExperimentalApi) -> tuple[str | None, str | None]:
    """Return images for the edge-endpoint and inference-server containers.
    """

    images_map = get_container_images_map(gl)

    # Find inference server image
    inference_image: str | None = None
    for containers in images_map.values():
        if isinstance(containers, dict) and 'inference-server' in containers:
            inference_image = containers['inference-server']
            break

    # Find edge-endpoint pod's image(s)
    edge_image: str | None = None
    for pod_name, containers in images_map.items():
        if pod_name == 'edge-endpoint' or pod_name.startswith('edge-endpoint'):
            edge_image = containers.get('edge-endpoint')
            break

    return edge_image, inference_image

def get_or_create_count_detector(
    gl: ExperimentalApi,
    name: str,
    class_name: str,
    max_count: int, 
    group_name: str,
    edge_pipeline_config: str | None = None,
    ) -> Detector:
    """Create a counting detector or return an existing one with the same name if it already exists."""

    query_text = f"Count all the {class_name}s"
    try:
        return gl.create_counting_detector(
            name,
            query_text,
            class_name,
            max_count=max_count,
            group_name=group_name,
            edge_pipeline_config=edge_pipeline_config,
        )
    except ApiException as e:
        if e.status != 400 or "unique_undeleted_name_per_set" not in getattr(e, "body", ""):
            raise
        return gl.get_detector_by_name(name)

def get_or_create_bounding_box_detector(
    gl: ExperimentalApi,
    name: str,
    class_name: str,
    max_num_bboxes: int = 10,
    group_name: str = "Load Testing",
    edge_pipeline_config: str | None = None,
) -> Detector:
    """Create a bounding box detector or return an existing one with the same name."""
    query_text = f"Draw a bounding box around each {class_name}"
    try:
        return gl.create_bounding_box_detector(
            name,
            query_text,
            class_name,
            max_num_bboxes=max_num_bboxes,
            group_name=group_name,
            edge_pipeline_config=edge_pipeline_config,
        )
    except ApiException as e:
        if e.status != 400 or "unique_undeleted_name_per_set" not in getattr(e, "body", ""):
            raise
        return gl.get_detector_by_name(name)

def get_or_create_multi_class_detector(
    gl: ExperimentalApi,
    name: str,
    class_names: list[str],
    group_name: str = "Load Testing",
    edge_pipeline_config: str | None = None,
) -> Detector:
    """Create a multi-class detector or return an existing one with the same name."""
    query_text = f"Which class is in the image? One of: {', '.join(class_names)}"
    try:
        return gl.create_multiclass_detector(
            name,
            query_text,
            class_names=class_names,
            group_name=group_name,
            edge_pipeline_config=edge_pipeline_config,
        )
    except ApiException as e:
        if e.status != 400 or "unique_undeleted_name_per_set" not in getattr(e, "body", ""):
            raise
        return gl.get_detector_by_name(name)


def error_if_not_from_edge(iq: ImageQuery) -> None:
    """Raise an error if the provided ImageQuery result did not originate from the Edge Endpoint."""
    if not iq.result.from_edge:
        raise ValueError(
            'Got a non-edge answer from the Edge Endpoint. '
            f'Please configure your Edge Endpoint so that {iq.detector_id} always receives edge answers.'
        )

def error_if_endpoint_is_cloud(gl: ExperimentalApi) -> None:
    """Raise if the connected endpoint appears to be the Groundlight cloud instead of an Edge Endpoint."""
    gl_endpoint = gl.endpoint
    host = (urlparse(gl_endpoint).hostname or "").lower()
    is_cloud = host.startswith("api.") and host.endswith(".groundlight.ai")
    if is_cloud:
        raise RuntimeError(
            f'You are connected to Groundlight cloud at {gl_endpoint}. This app should only be run against an Edge Endpoint. '
            'Please visit https://github.com/groundlight/edge-endpoint/blob/main/deploy/README.md to learn more about deploying an Edge Endpoint.'
        )

def prime_detector(
    gl: ExperimentalApi, 
    detector: Detector, 
    num_labels: int, 
    image_width: int, 
    image_height: int) -> None:
    """Submit synthetic labels in bounded concurrent batches to trigger model training."""

    def _prime_one() -> None:
        """Generate one sample, submit it, and attach the synthetic label."""
        image, label, rois = imgh.generate_random_image(gl, detector, image_width, image_height)
        iq = gl.submit_image_query(detector, image, **IQ_KWARGS_FOR_NO_ESCALATION)
        gl.add_label(iq, label, rois)

    remaining = num_labels
    with trange(num_labels, desc=f"Priming {detector.id} with {num_labels} labels.", unit="label") as progress:
        while remaining > 0:
            batch_size = min(PRIMING_MAX_BATCH_SIZE, remaining)
            with ThreadPoolExecutor(max_workers=batch_size) as executor:
                futures = [executor.submit(_prime_one) for _ in range(batch_size)]
                for future in futures:
                    future.result()
                    progress.update(1)
            remaining -= batch_size

def assert_configured_edge_pipeline_matches_provided(
    gl: ExperimentalApi, detector_id: str, expected_pipeline_config: str
) -> None:
    """Raise if the configured edge pipeline does not match the provided config."""
    configured_edge_pipeline = get_detector_edge_pipeline_configs(gl, detector_id).get("pipeline_config")
    if not _pipeline_configs_equal(expected_pipeline_config, configured_edge_pipeline):
        raise RuntimeError(
            f"The provided edge pipeline config does not match the detector's configured edge pipeline for {detector_id}. "
            "This can happen if the detector's pipeline config was changed after creation (e.g. via admin).\n"
            f"  Provided: {expected_pipeline_config!r}\n"
            f"  Configured edge: {configured_edge_pipeline!r}"
        )


def configure_edge_endpoint(
    gl: ExperimentalApi, detectors: Detector | list[Detector], *, edge_inference_config: InferenceConfig = NO_CLOUD,
) -> None:
    """Push an edge config for one or more detectors and wait for readiness."""
    if isinstance(detectors, Detector):
        detectors = [detectors]
    edge_config = EdgeEndpointConfig()
    for detector in detectors:
        edge_config.add_detector(detector, edge_inference_config)
    detector_ids = ", ".join(d.id for d in detectors)
    print(f"Configuring edge endpoint with [{detector_ids}] in {edge_inference_config.name} mode...")
    gl.edge.set_config(edge_config)
    print("Edge endpoint configured and inference ready.")


def get_detector_mode_default_cardinality(detector_mode: str) -> int:
    """Return the default cardinality used when the user does not specify one for the given mode."""
    if detector_mode == "BINARY":
        return 2
    if detector_mode == "COUNT":
        return 10
    if detector_mode == "BOUNDING_BOX":
        return 10
    if detector_mode == "MULTI_CLASS":
        return 4
    raise ValueError(f"Unsupported detector mode: {detector_mode}")


def get_detector_cardinality(detector: Detector) -> int:
    """Return the cardinality of an existing detector, read from its mode_configuration."""
    mode = detector.mode
    if mode == "BINARY":
        return get_detector_mode_default_cardinality(mode)

    config = detector.mode_configuration
    if mode == "COUNT":
        return int(config["max_count"])
    if mode == "BOUNDING_BOX":
        return int(config["max_num_bboxes"])
    if mode == "MULTI_CLASS":
        return len(config["class_names"])
    raise ValueError(f"Unsupported detector mode: {mode}")


def provision_detector(
    gl: ExperimentalApi,
    gl_cloud: ExperimentalApi,
    detector_mode: str,
    detector_name_prefix: str,
    image_width: int = 640,
    image_height: int = 480,
    group_name: str = "Load Testing",
    edge_pipeline_config: str | None = None,
    num_labels: int = 30,
    training_timeout_sec: float = 60 * 20,
    cardinality: int | None = None,
) -> Detector:
    """Create or fetch a detector, prime it if undertrained, and wait for training to finish.

    num_labels is the number of labels submitted during priming.
    gl_cloud is used for priming because the edge endpoint may already be in NO_CLOUD mode
    from a previous run, preventing labels from reaching cloud for training.

    cardinality is the user-provided override for the size of the detector's output/label space
    (max_count for COUNT, max_num_bboxes for BOUNDING_BOX, num_classes for MULTI_CLASS). When None,
    the per-mode default is used. BINARY's cardinality is fixed at 2; passing anything else for
    BINARY is rejected. The resolved value is appended to the detector name so different
    cardinalities create distinct detectors.
    """
    default_cardinality = get_detector_mode_default_cardinality(detector_mode)
    if detector_mode == "BINARY" and cardinality is not None and cardinality != default_cardinality:
        raise ValueError(
            f"--cardinality must be {default_cardinality} for BINARY detectors "
            "(BINARY has 2 labels by definition and cannot be changed)."
        )
    resolved_cardinality = cardinality if cardinality is not None else default_cardinality

    detector_name = f"{detector_name_prefix} {image_width} x {image_height} - {detector_mode}"
    if detector_mode != "BINARY":
        detector_name += f" - n{resolved_cardinality}"
    if edge_pipeline_config is not None:
        config_hash = hash_pipeline_config(edge_pipeline_config)
        detector_name += f" - {config_hash}"

    if detector_mode == "BINARY":
        detector = gl.get_or_create_detector(
            name=detector_name,
            query="Is the image background black?",
            group_name=group_name,
            edge_pipeline_config=edge_pipeline_config,
        )
    elif detector_mode == "COUNT":
        detector = get_or_create_count_detector(
            gl,
            name=detector_name,
            class_name="circle",
            max_count=resolved_cardinality,
            group_name=group_name,
            edge_pipeline_config=edge_pipeline_config,
        )
    elif detector_mode == "BOUNDING_BOX":
        detector = get_or_create_bounding_box_detector(
            gl,
            name=detector_name,
            class_name="circle",
            max_num_bboxes=resolved_cardinality,
            group_name=group_name,
            edge_pipeline_config=edge_pipeline_config,
        )
    elif detector_mode == "MULTI_CLASS":
        class_names = [str(i) for i in range(resolved_cardinality)]
        detector = get_or_create_multi_class_detector(
            gl,
            name=detector_name,
            class_names=class_names,
            group_name=group_name,
            edge_pipeline_config=edge_pipeline_config,
        )
    else:
        raise ValueError(f"Unsupported detector mode: {detector_mode}")

    if edge_pipeline_config is not None:
        assert_configured_edge_pipeline_matches_provided(gl, detector.id, edge_pipeline_config)

    # The pipeline may train before all submitted labels have been ingested,
    # so we accept a lower threshold when checking training completeness.
    min_training_labels = int(num_labels * 0.75)

    pipeline_details = get_edge_pipeline_details(gl, detector.id)
    if not edge_pipeline_is_sufficiently_trained(pipeline_details, min_training_labels):
        print(
            f"Edge pipeline for {detector.id} is not sufficiently trained "
            f"(trained_at={pipeline_details.get('trained_at')}, label_cnt={pipeline_details.get('label_cnt')}). "
            f"Priming with {num_labels} labels."
        )
        prime_detector(gl_cloud, detector, num_labels, image_width, image_height)
        print(f"Waiting up to {training_timeout_sec}s for edge pipeline training for {detector.id}...")
        wait_for_edge_pipeline_trained(
            gl, detector, min_training_labels, timeout_sec=training_timeout_sec
        )

    return detector


def edge_pipeline_is_sufficiently_trained(pipeline_details: dict, min_training_labels: int) -> bool:
    """Return True if the edge pipeline has trained with enough labels.

    Uses trained_at (set when the pipeline actually trains) and label_cnt from the
    MLBinary metadata. Works uniformly across all detector modes.
    """
    label_cnt = pipeline_details.get("label_cnt") or 0
    has_trained = pipeline_details.get("trained_at") is not None
    return has_trained and label_cnt >= min_training_labels

def wait_for_edge_pipeline_trained(
    gl: ExperimentalApi,
    detector: Detector,
    min_training_labels: int,
    timeout_sec: float,
    poll_interval_sec: float = 5.0,
) -> dict:
    """Poll until the edge pipeline has trained with enough labels, or timeout."""
    start = time.time()
    while True:
        pipeline_details = get_edge_pipeline_details(gl, detector.id)
        if edge_pipeline_is_sufficiently_trained(pipeline_details, min_training_labels):
            return pipeline_details

        if (time.time() - start) > timeout_sec:
            raise RuntimeError(
                f"Edge pipeline for {detector.id} did not train sufficiently after {timeout_sec}s. "
                f"Last status: trained_at={pipeline_details.get('trained_at')}, label_cnt={pipeline_details.get('label_cnt')}"
            )

        time.sleep(poll_interval_sec)
