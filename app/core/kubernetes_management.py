import logging
import os
from datetime import datetime

import yaml
from fastapi import status
from kubernetes import client as kube_client
from kubernetes import config
from kubernetes.client import V1Deployment

from .edge_inference import get_edge_inference_deployment_name, get_edge_inference_service_name
from .file_paths import INFERENCE_DEPLOYMENT_TEMPLATE_PATH, KUBERNETES_NAMESPACE_PATH

logger = logging.getLogger(__name__)


class InferenceDeploymentManager:
    def __init__(self) -> None:
        self._setup_kube_client()
        self._inference_deployment_template = self._load_inference_deployment_template()

    def _setup_kube_client(self) -> None:
        """Sets up the kubernetes client in order to access resources in the cluster."""
        # Requires the application to be running inside kubernetes.
        config.load_incluster_config()

        # Kubernetes resources are split across various API groups based on their functionality.
        # The `AppsV1Api` client manages resources related to workloads, such as Deployments, StatefulSets, etc.
        # The `CoreV1Api` client, on the other hand, handles core cluster resources like Pods, Services, and Namespaces.
        # Using both clients in order to create the deployment and service for the inference containers.
        self._app_kube_client = kube_client.AppsV1Api()
        self._core_kube_client = kube_client.CoreV1Api()

        if not os.path.exists(KUBERNETES_NAMESPACE_PATH):
            raise FileNotFoundError(f"Could not find kubernetes namespace file at {KUBERNETES_NAMESPACE_PATH}.")
        with open(KUBERNETES_NAMESPACE_PATH, "r") as f:
            self._target_namespace = f.read().strip()
        logger.info(f"Using {self._target_namespace} namespace.")

    def _load_inference_deployment_template(self) -> str:
        """Loads the inference deployment template."""
        if os.path.exists(INFERENCE_DEPLOYMENT_TEMPLATE_PATH):
            with open(INFERENCE_DEPLOYMENT_TEMPLATE_PATH, "r") as f:
                return f.read()

        raise FileNotFoundError(
            f"Could not find k3s inference deployment template at {INFERENCE_DEPLOYMENT_TEMPLATE_PATH}"
        )

    def _create_from_kube_manifest(self, namespace: str, manifest: str) -> None:
        """
        Applies manifest to the kubernetes namespace. This is not blocking since the kubernetes API
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

    def _substitute_placeholders(self, service_name: str, deployment_name: str, model_name: str) -> str:
        inference_deployment = self._inference_deployment_template
        inference_deployment = inference_deployment.replace("placeholder-inference-service-name", service_name)
        inference_deployment = inference_deployment.replace("placeholder-inference-deployment-name", deployment_name)

        inference_deployment = inference_deployment.replace(
            "placeholder-inference-instance-name", f"instance-{model_name}"
        )

        inference_deployment = inference_deployment.replace("placeholder-model-name", model_name)
        return inference_deployment.strip()

    def create_inference_deployment(self, detector_id: str, is_oodd: bool = False) -> None:
        """
        Creates an inference deployment (primary or OODD) for a given detector ID.

        This method substitutes placeholders in the inference deployment template
        with the provided detector ID, service name, and deployment name, and then
        applies the manifest to the Kubernetes namespace.

        Args:
            detector_id (str): The unique identifier for the detector for which
                               the inference deployment is to be created.
            is_oodd (bool): Whether to create an OODD inference deployment.
        """
        deployment_name = get_edge_inference_deployment_name(detector_id, is_oodd)
        service_name = get_edge_inference_service_name(detector_id, is_oodd)
        model_name = get_edge_inference_model_name(detector_id, is_oodd)
        inference_deployment = self._substitute_placeholders(
            service_name=service_name, deployment_name=deployment_name, model_name=model_name
        )
        self._create_from_kube_manifest(namespace=self._target_namespace, manifest=inference_deployment)

    def get_inference_deployment(self, deployment_name: str) -> V1Deployment | None:
        """
        Retrieves the inference deployment for a given deployment name.

        Args:
            detector_id (str): The unique identifier for the detector whose inference deployment
                               is to be retrieved.

        Returns:
            Optional[V1Deployment]: The deployment object if it exists, otherwise None.
        """
        try:
            deployment = self._app_kube_client.read_namespaced_deployment(
                name=deployment_name, namespace=self._target_namespace
            )
            return deployment
        except kube_client.rest.ApiException as e:
            if e.status == status.HTTP_404_NOT_FOUND:
                logger.debug(
                    f"Deployment {deployment_name} does not currently exist in namespace {self._target_namespace}."
                )
                return None
            raise e

    def get_or_create_inference_deployment(self, detector_id: str, is_oodd: bool = False) -> V1Deployment | None:
        """
        Retrieves an existing inference deployment for the specified detector ID, or creates a new
        one if it does not exist.

        Args:
            detector_id (str): The unique identifier for the detector whose inference deployment
                               is to be retrieved or created.
            is_oodd (bool): Whether the inference deployment is for an OODD model.

        Returns:
            Optional[V1Deployment]: The existing deployment if found, otherwise None if a new
                                    deployment is created.
        """
        deployment_name = get_edge_inference_deployment_name(detector_id, is_oodd)
        deployment = self.get_inference_deployment(deployment_name)
        if deployment is not None:
            return deployment

        logger.debug(f"Deployment for {detector_id} with deployment name {deployment_name} does not currently exist in namespace {self._target_namespace}.")
        self.create_inference_deployment(detector_id=detector_id, is_oodd=is_oodd)
        return None

    def update_inference_deployment(self, detector_id: str, is_oodd: bool = False) -> bool:
        """
        Updates the inference deployment for a given detector ID.

        This method checks if an inference deployment already exists for the specified detector ID.
        If it does not exist, it creates a new deployment. If it exists, it updates the deployment
        by setting the appropriate environment variables and annotations to ensure the correct model
        is loaded and the deployment is restarted.

        Args:
            detector_id (str): The unique identifier for the detector whose inference deployment
                               needs to be updated.
            is_oodd (bool): Whether the inference deployment is for an OODD model.

        Returns:
            bool: True if the deployment was updated, False if a new deployment was created.
        """
        deployment_name = get_edge_inference_deployment_name(detector_id, is_oodd)
        deployment = self.get_or_create_inference_deployment(detector_id, is_oodd)
        if deployment is None:
            logger.info(f"Creating a new inference deployment: {deployment_name}")
            return False

        if deployment.spec.template.metadata.annotations is None:
            deployment.spec.template.metadata.annotations = {}
        deployment.spec.template.metadata.annotations["kubectl.kubernetes.io/restartedAt"] = datetime.now().isoformat()

        # Set the correct model name for this inference deployment
        for env_var in deployment.spec.template.spec.containers[0].env:
            if env_var.name == "MODEL_NAME":
                model_name = get_edge_inference_model_name(detector_id, is_oodd)
                env_var.value = model_name
                break

        logger.info(f"Patching an existing inference deployment: {deployment_name}")
        self._app_kube_client.patch_namespaced_deployment(
            name=deployment_name, namespace=self._target_namespace, body=deployment
        )
        return True

    def is_inference_deployment_rollout_complete(self, deployment_name: str) -> bool:
        """
        Checks if the rollout of the inference deployment for a given deployment name is complete.

        This method retrieves the deployment associated with the specified detector ID and compares
        the desired number of replicas with the updated and available replicas. If all these values
        match, it indicates that the deployment rollout is complete.

        Args:
            deployment_name (str): The name of the deployment whose rollout status needs to be 
                checked.

        Returns:
            bool: True if the deployment rollout is complete, False otherwise.
        """

        # Fetch the Deployment object
        deployment = self.get_inference_deployment(deployment_name)
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
