"""Naming conventions for edge inference resources (K8s deployments, services, model paths)."""

import os


def get_edge_inference_service_name(detector_id: str, is_oodd: bool = False) -> str:
    """Kubernetes service names must be alphanumeric, lower-cased, and can only contain dashes."""
    return f"inference-service-{'oodd' if is_oodd else 'primary'}-{detector_id.replace('_', '-').lower()}"


def get_edge_inference_deployment_name(detector_id: str, is_oodd: bool = False) -> str:
    return f"inferencemodel-{'oodd' if is_oodd else 'primary'}-{detector_id.replace('_', '-').lower()}"


def get_edge_inference_model_name(detector_id: str, is_oodd: bool = False) -> str:
    return os.path.join(detector_id, "primary" if not is_oodd else "oodd")


def get_detector_models_dir(repository_root: str, detector_id: str) -> str:
    return os.path.join(repository_root, detector_id)


def get_primary_edge_model_dir(repository_root: str, detector_id: str) -> str:
    return os.path.join(get_detector_models_dir(repository_root, detector_id), "primary")


def get_oodd_model_dir(repository_root: str, detector_id: str) -> str:
    return os.path.join(get_detector_models_dir(repository_root, detector_id), "oodd")
