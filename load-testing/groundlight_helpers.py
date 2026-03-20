from groundlight import ExperimentalApi, Detector, ApiException, ImageQuery

from groundlight_openapi_client.exceptions import ApiTypeError

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

# Image query submission args that will ensure a query is never escalated to the cloud, 
# unless an inference pod doesn't exist for the detector, in which case we have no choice but to escalate
IQ_KWARGS_FOR_NO_ESCALATION = {'wait': 0.0, 'human_review': 'NEVER', 'confidence_threshold': 0.0}
IQ_KWARGS_NON_HUMAN_CLOUD_ESCALATION = {'wait': 0.0, 'human_review': 'NEVER', 'confidence_threshold': 1.0}
PRIMING_MAX_BATCH_SIZE = 10

PIPELINE_LOADED_TIMEOUT_SEC = 60 * 3


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

def get_detector_evaluation(gl: ExperimentalApi, detector_id: str) -> dict:
    """
    Get the detector evaluation stats that we will use to determine if a detector is
    sufficiently trained, i.e. `kfold_pooled__balanced_accuracy` and `total_ground_truth_examples`
    """

    full_detector_evaluation = gl.get_detector_evaluation(detector_id)
    if full_detector_evaluation is None:
        kfold_pooled__balanced_accuracy = None
        total_ground_truth_examples = None
    else:
        evaluation_results = full_detector_evaluation.get('evaluation_results')
        if evaluation_results is None:
            kfold_pooled__balanced_accuracy = None
            total_ground_truth_examples = None
        else:
            kfold_pooled__balanced_accuracy = evaluation_results.get('kfold_pooled__balanced_accuracy')
            total_ground_truth_examples = evaluation_results.get('total_ground_truth_examples')
    return {
        "projected_ml_accuracy": kfold_pooled__balanced_accuracy,
        "total_labels": total_ground_truth_examples,
        }

def call_edge_api(gl_client: ExperimentalApi, path: str, params: dict) -> dict:

    url = gl_client.endpoint.replace('/device-api', '/edge-api') + path

    return call_api(url, params)

def get_detector_pipeline_configs(gl: ExperimentalApi, detector_id: str) -> dict:
    """
    Get the detector pipeline configs that have been trained in the cloud for the Edge Endpoint.

    These haven't necessary been downloaded to the Edge Endpoint yet; they simply represent the 
    latest available pipeline config in the cloud for the Edge Endpoint. 
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

def wait_for_edge_answer(
    gl: ExperimentalApi,
    detector: Detector,
    image_width: int,
    image_height: int,
    timeout_sec: float,
) -> None:
    """Waits until the inference pod returns at least one edge answer."""
    image, _, _ = imgh.generate_random_image(gl, detector, image_width, image_height)
    _ = gl.submit_image_query(detector, image, **IQ_KWARGS_FOR_NO_ESCALATION)

    poll_start = time.time()
    while True:
        elapsed_time = time.time() - poll_start
        if elapsed_time > timeout_sec:
            raise RuntimeError(
                f"Inference pod for {detector.id} did not return an edge answer after {timeout_sec:.2f} seconds."
            )
        image, _, _ = imgh.generate_random_image(gl, detector, image_width, image_height)
        iq = gl.submit_image_query(detector, image, **IQ_KWARGS_FOR_NO_ESCALATION)
        if iq.result.from_edge:
            return
        time.sleep(5)


def assert_cloud_pipeline_matches_provided(
    gl: ExperimentalApi, detector_id: str, expected_pipeline_config: str
) -> None:
    """Raises if the cloud pipeline config does not match the provided config."""
    cloud_config = get_detector_pipeline_configs(gl, detector_id).get("pipeline_config")
    if not _pipeline_configs_equal(expected_pipeline_config, cloud_config):
        raise RuntimeError(
            f"The pipeline_config provided does not match the pipeline_config in the cloud for detector {detector_id}. "
            "This can happen if the detector's pipeline config was changed after creation (e.g. via admin).\n"
            f"  Provided: {expected_pipeline_config!r}\n"
            f"  Cloud:    {cloud_config!r}"
        )


def assert_loaded_pipeline_matches_provided(
    gl: ExperimentalApi, detector_id: str, expected_pipeline_config: str
) -> None:
    """Raises if the pipeline loaded on the edge does not match the expected config."""
    loaded = (get_detector_edge_metrics(gl, detector_id) or {}).get("pipeline_config")
    if not _pipeline_configs_equal(expected_pipeline_config, loaded):
        raise RuntimeError(
            f"The pipeline config provided does not match the pipeline loaded for detector {detector_id}. "
            "This can happen if the detector's pipeline config was changed after creation (e.g. via admin).\n"
            f"  Provided: {expected_pipeline_config!r}\n"
            f"  Loaded:   {loaded!r}"
        )


def wait_for_loaded_pipeline_to_match_cloud(
    gl: ExperimentalApi, detector_id: str, timeout_sec: float = PIPELINE_LOADED_TIMEOUT_SEC
) -> None:
    """After an edge answer exists, waits until the cloud pipeline config is loaded locally."""
    cloud_configs = get_detector_pipeline_configs(gl, detector_id)
    expected = cloud_configs.get("pipeline_config")
    poll_start = time.time()
    while True:
        elapsed = time.time() - poll_start
        if elapsed > timeout_sec:
            loaded = (get_detector_edge_metrics(gl, detector_id) or {}).get("pipeline_config")
            raise RuntimeError(
                f"Pipeline for detector {detector_id} did not match cloud config within {timeout_sec:.2f} seconds. "
                "The detector's pipeline config may have been changed after creation (e.g. via admin).\n"
                f"  Cloud:  {expected!r}\n"
                f"  Loaded: {loaded!r}"
            )
        loaded = (get_detector_edge_metrics(gl, detector_id) or {}).get("pipeline_config")
        if _pipeline_configs_equal(expected, loaded):
            return
        time.sleep(5)


def wait_for_ready_inference_pod(
    gl: ExperimentalApi,
    detector: Detector,
    image_width: int,
    image_height: int,
    timeout_sec: float,
    edge_pipeline_config: str | None = None,
) -> None:
    """Waits for an edge answer, then ensures the loaded pipeline matches (provided or cloud)."""
    wait_for_edge_answer(gl, detector, image_width, image_height, timeout_sec)
    if edge_pipeline_config is not None:
        # If a pipeline config was provided, we expect the loaded pipeline config to match right away.
        # If it doesn't match, it likely means someone changed it in Admin, which would cause
        # the test to run with a pipeline other than what the user expects. We fail loudly if that happens.
        assert_loaded_pipeline_matches_provided(gl, detector.id, edge_pipeline_config)
    else:
        # When no pipeline config is provided, users are allowed to change the pipeline config in Admin; 
        # this workflow supports custom yaml pipelines, which aren't currently supported in the Python SDK. 
        # When a new pipeline is configured in Admin, it will take some time for the detector retrain,
        # and for the new pipeline to make its way to the egde. Therefore, we will wait here for a bit
        # to ensure that the edge pipeline configured in the cloud matches what was downloaded to the edge.
        wait_for_loaded_pipeline_to_match_cloud(gl, detector.id, timeout_sec=PIPELINE_LOADED_TIMEOUT_SEC)

def detector_is_sufficiently_trained(
    stats: dict,
    min_projected_ml_accuracy: float,
    min_total_labels: int,
    ) -> bool:
    """Return True if projected ML accuracy and label count exceed provided thresholds."""
    projected_ml_accuracy = stats['projected_ml_accuracy'] 
    total_labels = stats['total_labels'] 
    return projected_ml_accuracy is not None and \
        projected_ml_accuracy > min_projected_ml_accuracy and \
        total_labels >= min_total_labels

def wait_until_sufficiently_trained(
    gl: ExperimentalApi,
    detector: Detector,
    min_projected_ml_accuracy: float,
    min_total_labels: int,
    timeout_sec: float,
    poll_interval_sec: float = 5.0,
) -> dict:
    """Poll detector evaluation until it meets training thresholds or timeout, then return stats."""
    start = time.time()
    while True:
        stats = get_detector_evaluation(gl, detector.id)
        if detector_is_sufficiently_trained(stats, min_projected_ml_accuracy, min_total_labels):
            return stats

        if (time.time() - start) > timeout_sec:
            raise RuntimeError(
                f'{detector.id} failed to trained sufficiently after {timeout_sec} seconds.'
            )

        time.sleep(poll_interval_sec)
