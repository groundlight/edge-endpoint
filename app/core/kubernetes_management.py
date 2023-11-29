import logging
import os
from datetime import datetime
from typing import Optional

import yaml
from kubernetes import client as kube_client
from kubernetes import config

from .edge_inference import get_edge_inference_deployment_name, get_edge_inference_service_name
from .file_paths import INFERENCE_DEPLOYMENT_TEMPLATE_PATH
from .utils import prefixed_ksuid

logger = logging.getLogger(__name__)


class InferenceDeploymentManager:
    def __init__(self) -> None:
        self._setup_kube_client()
        self._inference_deployment_template = self._load_inference_deployment_template()

    def _setup_kube_client(self) -> None:
        """
        Sets up the kubernetes client in order to access resources in the cluster.
        """

        # Requires the application to be running inside kubernetes.
        config.load_incluster_config()

        # Kubernetes resources are split across various API groups based on their functionality.
        # The `AppsV1Api` client manages resources related to workloads, such as Deployments, StatefulSets, etc.
        # The `CoreV1Api` client, on the other hand, handles core cluster resources like Pods, Services, and Namespaces.
        # Using both clients in order to create the deployment and service for the inference containers.
        self._app_kube_client = kube_client.AppsV1Api()
        self._core_kube_client = kube_client.CoreV1Api()

        deployments = self._app_kube_client.list_deployment_for_all_namespaces(
            label_selector="app=edge-logic-server", field_selector="metadata.name=edge-endpoint"
        )
        self._target_namespace = deployments.items[0].metadata.namespace if deployments.items else "default"

    def _load_inference_deployment_template(self) -> str:
        """
        Loads the inference deployment template.
        """
        if os.path.exists(INFERENCE_DEPLOYMENT_TEMPLATE_PATH):
            with open(INFERENCE_DEPLOYMENT_TEMPLATE_PATH, "r") as f:
                return f.read()

        raise FileNotFoundError(
            f"Could not find k3s inference deployment template at {INFERENCE_DEPLOYMENT_TEMPLATE_PATH}"
        )

    def _create_from_kube_manifest(self, namespace: str, manifest: str) -> None:
        """
        Applies manifest to the kubernetes cluster. This is not blocking since the kubernetes API
        creates deployments and services asynchronously.
        """
        logger.debug(f"Applying kubernetes manifest to namespace `{namespace}`...")
        for document in yaml.safe_load_all(manifest):
            try:
                if document["kind"] == "Service":
                    self._core_kube_client.create_namespaced_service(namespace=namespace, body=document)
                elif document["kind"] == "Deployment":
                    self._app_kube_client.create_namespaced_deployment(namespace=namespace, body=document)
                else:
                    raise NotImplementedError(f"Unsupported kubernetes manifest kind: {document['kind']}")

            except kube_client.rest.ApiException as e:
                if e.status == 409:
                    logger.error(f"Failed to create a kubernetes service or deployment because it already exists: {e}")
                else:
                    raise e

    def _substitute_placeholders(self, service_name: str, deployment_name: str, detector_id: str) -> str:
        inference_deployment = self._inference_deployment_template
        inference_deployment = inference_deployment.replace("placeholder-inference-service-name", service_name)
        inference_deployment = inference_deployment.replace("placeholder-inference-deployment-name", deployment_name)
        inference_deployment = inference_deployment.replace("placeholder-model-name", detector_id)
        return inference_deployment.strip()

    def create_inference_deployment(self, detector_id) -> None:
        deployment_name = get_edge_inference_deployment_name(detector_id)
        service_name = get_edge_inference_service_name(detector_id)
        inference_deployment = self._substitute_placeholders(
            service_name=service_name, deployment_name=deployment_name, detector_id=detector_id
        )
        self._create_from_kube_manifest(namespace=self._target_namespace, manifest=inference_deployment)

    def get_inference_deployment(self, detector_id) -> Optional["V1Deployment"]:
        deployment_name = get_edge_inference_deployment_name(detector_id)
        try:
            deployment = self._app_kube_client.read_namespaced_deployment(
                name=deployment_name, namespace=self._target_namespace
            )
            return deployment
        except kube_client.rest.ApiException as e:
            if e.status == 404:
                logger.debug(
                    f"Deployment {deployment_name} does not currently exist in namespace {self._target_namespace}."
                )
                return None
            raise e

    def get_or_create_inference_deployment(self, detector_id) -> Optional["V1Deployment"]:
        deployment = self.get_inference_deployment(detector_id)
        if deployment is not None:
            return deployment

        logger.debug(f"Deployment for {detector_id} does not currently exist in namespace {self._target_namespace}.")
        self.create_inference_deployment(detector_id)
        return None

    def update_inference_deployment(self, detector_id: str) -> bool:
        deployment_name = get_edge_inference_deployment_name(detector_id)
        deployment = self.get_or_create_inference_deployment(detector_id)
        if deployment is None:
            logger.info(f"Creating a new inference deployment: {deployment_name}")
            return False

        if deployment.spec.template.metadata.annotations is None:
            deployment.spec.template.metadata.annotations = {}
        deployment.spec.template.metadata.annotations["kubectl.kubernetes.io/restartedAt"] = datetime.now().isoformat()

        # Set the correct detector_id so we dont load more than the one model in this deployment. Also rotate the shm-region.
        deployment.spec.template.spec.containers[0].command = [
            "tritonserver",
            "--model-repository=/mnt/models",
            f"--load-model={detector_id}",  # Only load the model we care about
            "--metrics-config=summary_latencies=true",
            "--allow-cpu-metrics=true",
            "--allow-gpu-metrics=true",
            "--model-control-mode=explicit",
            f"--backend-config=python,shm-region-prefix-name={deployment_name}",
            "--log-verbose=1",
        ]

        logger.info(f"Patching an existing inference deployment: {deployment_name}")
        self._app_kube_client.patch_namespaced_deployment(
            name=deployment_name, namespace=self._target_namespace, body=deployment
        )
        return True

    def is_inference_deployment_rollout_complete(self, detector_id: str) -> bool:
        # Fetch the Deployment object
        deployment = self.get_inference_deployment(detector_id)
        if deployment is None:
            return False

        desired_replicas = deployment.spec.replicas
        updated_replicas = deployment.status.updated_replicas if deployment.status.updated_replicas else 0
        available_replicas = deployment.status.available_replicas if deployment.status.available_replicas else 0

        if desired_replicas == updated_replicas == available_replicas:
            logger.info(f"Inference deployment for {detector_id} is ready")
            return True
        logger.debug(
            f"Inference deployment rollout for {detector_id} is not complete. Desired: {desired_replicas}, Updated:"
            f" {updated_replicas}, Available: {available_replicas}"
        )
        return False
