from groundlight import ExperimentalApi, Detector, ApiException, ImageQuery

import os
import requests
import json
import time
from tqdm import trange

import image_helpers as imgh

CLOUD_ENDPOINT = 'https://api.groundlight.ai/device-api'

# Image query submission args that will ensure a query is never escalated to the cloud, 
# unless an inference pod doesn't exist for the detector, in which case we have no choice but to escalate
IQ_KWARGS_FOR_NO_ESCALATION = {'wait': 0.0, 'human_review': 'NEVER', 'confidence_threshold': 0.0}

# We need to establish a client here so that we can use functions like `gl.create_roi`, but we won't
# actually use it to submit anything to Groundlight
gl = ExperimentalApi(endpoint=None)

class APIError(Exception):
    """Any response from the Groundlight API that is not 200
    """
    pass

def call_api(url: str, params: dict) -> dict:

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

def call_reef_api(gl_client: ExperimentalApi, path: str, params: dict) -> dict:

    url = gl_client.endpoint.replace('/device-api', '/reef-api') + path

    return call_api(url, params)

def call_edge_api(gl_client: ExperimentalApi, path: str, params: dict) -> dict:

    url = gl_client.endpoint.replace('/device-api', '/edge-api') + path

    return call_api(url, params)

def get_detector_stats(gl: ExperimentalApi, detector_id: str) -> dict:
    path = f'/detectors/{detector_id}'
    params = {
        'type': 'summary',
        'answer_type': 'current_best_answer',
    }
    
    decoded_response = call_reef_api(gl, path, params)
        
    evaluation_results = decoded_response.get('evaluation_results')
    if evaluation_results is None:
        projected_ml_accuracy = None
        total_ground_truth_examples = 0
    else:
        projected_ml_accuracy = evaluation_results['kfold_pooled__balanced_accuracy']
        total_ground_truth_examples = evaluation_results["total_ground_truth_examples"]


    return {
        "projected_ml_accuracy": projected_ml_accuracy,
        "total_labels": total_ground_truth_examples,
        }

def get_detector_pipeline_configs(gl: ExperimentalApi, detector_id: str) -> dict:
    path = f'/v1/fetch-model-urls/{detector_id}/'
    params = {}
    
    decoded_response = call_edge_api(gl, path, params)

    return {
        "pipeline_config": decoded_response.get('pipeline_config'),
        "oodd_pipeline_config": decoded_response.get('oodd_pipeline_config'),
    }

def get_detector_edge_metrics(gl: ExperimentalApi, detector_id: str) -> dict | None:
    metrics = _get_status_metrics(gl)
    return (metrics.get('detector_details') or {}).get(detector_id)

def _get_status_metrics(gl: ExperimentalApi) -> dict:
    base = gl.endpoint.replace('/device-api', '')
    url = base + '/status/metrics.json'
    return call_api(url, {})

def get_container_images_map(gl: ExperimentalApi) -> dict[str, dict[str, str]]:
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
    ) -> list[Detector]:

    query_text = f"Count all the {class_name}s"
    try:
        return gl.create_counting_detector(
            name,
            query_text,
            class_name,
            max_count=max_count,
            group_name=group_name,
        )
    except ApiException as e:
        if e.status != 400 or "unique_undeleted_name_per_set" not in getattr(e, "body", ""):
            raise
        return gl.get_detector_by_name(name)

def error_if_not_from_edge(iq: ImageQuery) -> None:
    if not iq.result.from_edge:
        raise ValueError(
            'Got a non-edge answer from the Edge Endpoint. '
            f'Please configure your Edge Endpoint so that {iq.detector_id} always receives edge answers.'
        )

def error_if_endpoint_is_cloud(gl: ExperimentalApi) -> None:
    if CLOUD_ENDPOINT == gl.endpoint:
        raise RuntimeError(
            'You are connected to Groundlight cloud. This app should only be run against an Edge Endpoint. '
            'Please visit https://github.com/groundlight/edge-endpoint/blob/main/deploy/README.md to learn more about deploying an Edge Endpoint.'
        )

def prime_detector(
    gl: ExperimentalApi, 
    detector: Detector, 
    num_labels: int, 
    image_width: int, 
    image_height: int) -> None:
    """
    Submits a handful of labels to a detector so that the cloud can train a model. 
    """
    for _ in trange(num_labels, desc=f"Priming {detector.id} with {num_labels} labels.", unit="label"):
        image, label, rois = imgh.generate_random_image(gl, detector, image_width, image_height)
        # iq = gl.ask_async(detector, image, human_review="NEVER") # using ask_sync is causing a race condition on the server, commmenting it out until that is fixed
        iq = gl.submit_image_query(detector, image, **IQ_KWARGS_FOR_NO_ESCALATION)
        gl.add_label(iq, label, rois)

def wait_for_ready_inference_pod(
    gl: ExperimentalApi,
    detector: Detector,
    image_width: int, 
    image_height: int,
    pipeline_config: str,
    timeout_sec: float,
    ) -> None:
    """
    Waits until an inference pod is ready for the given detector.

    Uses receiving an edge answer as a proxy for there being a ready inference pod.
    """

    poll_start = time.time()
    while True:
        elapsed_time = time.time() - poll_start
        if elapsed_time > timeout_sec:
            raise RuntimeError(
                f"Failed to roll out inference pod for {detector.id} with pipeline_config='{pipeline_config}' after {timeout_sec:.2f} seconds."
            )

        detector_edge_metrics = get_detector_edge_metrics(gl, detector.id)
        if detector_edge_metrics is None:
            # Trigger pod creation by submitting an image query
            image, _, _ = imgh.generate_random_image(gl, detector, image_width, image_height)
            _ = gl.submit_image_query(
                detector, 
                image, 
                **IQ_KWARGS_FOR_NO_ESCALATION) 
        else:
            pod_status = detector_edge_metrics.get('status')
            edge_pipeline_config = detector_edge_metrics.get('pipeline_config')

            # Check that the pod is ready and is using the specified pipeline_config
            if pod_status == 'ready' and pipeline_config == edge_pipeline_config:
                return

        # Inference pod is not yet ready. Wait and retry
        time.sleep(5)

def detector_is_sufficiently_trained(
    stats: dict,
    min_projected_ml_accuracy: float,
    min_total_labels: int,
    ) -> bool:
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
    start = time.time()
    while True:
        stats = get_detector_stats(gl, detector.id)
        if detector_is_sufficiently_trained(stats, min_projected_ml_accuracy, min_total_labels):
            return stats

        if (time.time() - start) > timeout_sec:
            raise RuntimeError(
                f'{detector.id} failed to trained sufficiently after {timeout_sec} seconds.'
            )

        time.sleep(poll_interval_sec)
