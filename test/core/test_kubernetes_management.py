from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client import (
    V1Deployment,
    V1DeploymentSpec,
    V1LabelSelector,
    V1ObjectMeta,
    V1PodTemplateSpec,
    V1Service,
    V1ServiceSpec,
)
from kubernetes.client.rest import ApiException


def _make_manager():
    """Create an InferenceDeploymentManager with mocked-out __init__."""
    with patch("app.core.kubernetes_management.InferenceDeploymentManager.__init__", return_value=None):
        from app.core.kubernetes_management import InferenceDeploymentManager

        mgr = InferenceDeploymentManager()
        mgr._core_kube_client = MagicMock()
        mgr._app_kube_client = MagicMock()
        mgr._target_namespace = "edge"
        return mgr


def _make_deployment(*, replicas=1, updated=1, available=1, total=1):
    dep = MagicMock()
    dep.spec.replicas = replicas
    dep.status.updated_replicas = updated
    dep.status.available_replicas = available
    dep.status.replicas = total
    dep.spec.selector.match_labels = {"app": "test-det"}
    return dep


def _make_pod_list(count: int):
    pod_list = MagicMock()
    pod_list.items = [MagicMock() for _ in range(count)]
    return pod_list


class TestIsInferenceDeploymentRolloutComplete:
    def test_deployment_not_found(self):
        """Returns False when get_inference_deployment returns None (deployment deleted or not yet created)."""
        mgr = _make_manager()
        mgr.get_inference_deployment = MagicMock(return_value=None)
        assert mgr.is_inference_deployment_rollout_complete("test-dep") is False

    def test_replicas_not_yet_updated(self):
        """Returns False when desired/updated/available replica counts don't match yet.
        Skips the pod-listing check entirely since the rollout is clearly still in progress."""
        mgr = _make_manager()
        mgr.get_inference_deployment = MagicMock(
            return_value=_make_deployment(replicas=1, updated=0, available=0, total=1)
        )
        assert mgr.is_inference_deployment_rollout_complete("test-dep") is False
        mgr._core_kube_client.list_namespaced_pod.assert_not_called()

    def test_complete_when_replicas_match_and_no_extra_pods(self):
        """Returns True when all replica counts equal 1 and only 1 pod exists (no terminating pods)."""
        mgr = _make_manager()
        mgr.get_inference_deployment = MagicMock(return_value=_make_deployment())
        mgr._core_kube_client.list_namespaced_pod.return_value = _make_pod_list(1)
        assert mgr.is_inference_deployment_rollout_complete("test-dep") is True

    def test_incomplete_when_terminating_pod_lingers(self):
        """Returns False when replica counts all equal 1 but 2 pods exist,
        indicating the old pod is still terminating and potentially holding GPU memory."""
        mgr = _make_manager()
        mgr.get_inference_deployment = MagicMock(return_value=_make_deployment())
        mgr._core_kube_client.list_namespaced_pod.return_value = _make_pod_list(2)
        assert mgr.is_inference_deployment_rollout_complete("test-dep") is False


TEMPLATE = """apiVersion: v1
kind: Service
metadata:
  name: placeholder-inference-service-name
spec:
  ports:
  - port: 8000
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: placeholder-inference-deployment-name
spec:
  template:
    metadata:
      labels:
        instance: placeholder-inference-instance-name
      annotations:
        groundlight.dev/inference-server: "triton"
    spec:
      containers:
      - name: inference-server
        image: gl-edge-inference:abc123-triton
        env:
        - name: MODEL_NAME
          value: placeholder-model-name
"""


def _deployment_with_annotations(annotations: dict | None):
    dep = MagicMock()
    dep.spec.template.metadata.annotations = annotations
    return dep


class TestDeploymentInferenceServer:
    def test_reads_the_pod_template_annotation(self):
        from app.core.inference_server import InferenceServer
        from app.core.kubernetes_management import InferenceDeploymentManager

        dep = _deployment_with_annotations({"groundlight.dev/inference-server": "triton"})
        assert InferenceDeploymentManager.deployment_inference_server(dep) is InferenceServer.TRITON

    def test_pods_without_the_annotation_run_fastapi(self):
        """Deployments created before the annotation existed run FastAPI."""
        from app.core.inference_server import InferenceServer
        from app.core.kubernetes_management import InferenceDeploymentManager

        for annotations in (None, {"groundlight.dev/model-version": "3"}):
            dep = _deployment_with_annotations(annotations)
            assert InferenceDeploymentManager.deployment_inference_server(dep) is InferenceServer.FASTAPI


class TestDeploymentGpuSharing:
    def test_reads_the_pod_template_annotation(self):
        from app.core.gpu_sharing import GpuSharing
        from app.core.kubernetes_management import InferenceDeploymentManager

        dep = _deployment_with_annotations({"groundlight.dev/gpu-sharing": "mps"})
        assert InferenceDeploymentManager.deployment_gpu_sharing(dep) is GpuSharing.MPS

    def test_pods_without_the_annotation_do_not_use_mps(self):
        from app.core.gpu_sharing import GpuSharing
        from app.core.kubernetes_management import InferenceDeploymentManager

        for annotations in (None, {"groundlight.dev/inference-server": "triton"}):
            dep = _deployment_with_annotations(annotations)
            assert InferenceDeploymentManager.deployment_gpu_sharing(dep) is GpuSharing.NONE


class TestDeploymentGpuPlacement:
    def test_reads_the_pod_template_annotation(self):
        from app.core.gpu_placement import GpuPlacement
        from app.core.kubernetes_management import InferenceDeploymentManager

        dep = _deployment_with_annotations({"groundlight.dev/gpu-placement": "ledger"})
        assert InferenceDeploymentManager.deployment_gpu_placement(dep) is GpuPlacement.LEDGER

    def test_pods_without_the_annotation_do_not_use_the_ledger(self):
        from app.core.gpu_placement import GpuPlacement
        from app.core.kubernetes_management import InferenceDeploymentManager

        for annotations in (None, {"groundlight.dev/inference-server": "triton"}):
            dep = _deployment_with_annotations(annotations)
            assert InferenceDeploymentManager.deployment_gpu_placement(dep) is GpuPlacement.NONE


class TestPodTemplateIsOutdated:
    @pytest.mark.parametrize(
        "annotations, server, sharing, outdated",
        [
            (
                {"groundlight.dev/inference-server": "triton", "groundlight.dev/gpu-sharing": "mps"},
                "triton",
                "mps",
                False,
            ),
            (
                {"groundlight.dev/inference-server": "triton", "groundlight.dev/gpu-sharing": "none"},
                "triton",
                "mps",
                True,
            ),
            ({"groundlight.dev/inference-server": "triton"}, "triton", "mps", True),
            (
                {"groundlight.dev/inference-server": "triton", "groundlight.dev/gpu-sharing": "mps"},
                "triton",
                "none",
                True,
            ),
            ({"groundlight.dev/inference-server": "fastapi"}, "triton", "none", True),
            ({"groundlight.dev/inference-server": "fastapi"}, "fastapi", "none", False),
            (None, "fastapi", "none", False),
        ],
    )
    def test_compares_server_and_sharing_annotations_with_the_configuration(
        self, monkeypatch: pytest.MonkeyPatch, annotations, server, sharing, outdated
    ):
        monkeypatch.setenv("INFERENCE_SERVER", server)
        monkeypatch.setenv("GPU_SHARING", sharing)
        monkeypatch.delenv("GPU_PLACEMENT", raising=False)
        mgr = _make_manager()

        assert mgr.pod_template_is_outdated(_deployment_with_annotations(annotations)) is outdated

    @pytest.mark.parametrize(
        "placement_annotation, placement, outdated",
        [
            ("ledger", "ledger", False),
            (None, "ledger", True),  # Created before the chart mounted the ledger.
            ("none", "ledger", True),
            ("ledger", "none", True),
            ("none", "none", False),
            (None, "none", False),
        ],
    )
    def test_compares_the_gpu_placement_annotation_with_the_configuration(
        self, monkeypatch: pytest.MonkeyPatch, placement_annotation, placement, outdated
    ):
        monkeypatch.setenv("INFERENCE_SERVER", "triton")
        monkeypatch.setenv("GPU_SHARING", "mps")
        monkeypatch.setenv("GPU_PLACEMENT", placement)
        annotations = {"groundlight.dev/inference-server": "triton", "groundlight.dev/gpu-sharing": "mps"}
        if placement_annotation is not None:
            annotations["groundlight.dev/gpu-placement"] = placement_annotation
        mgr = _make_manager()

        assert mgr.pod_template_is_outdated(_deployment_with_annotations(annotations)) is outdated


class TestRerenderInferenceDeployment:
    def test_replaces_the_pod_template_with_one_rendered_from_the_current_template(self):
        """A JSON patch replaces the whole pod template, so nothing from the old server is merged in."""
        from app.core.naming import get_edge_inference_deployment_name, get_edge_inference_model_name

        mgr = _make_manager()
        mgr._inference_deployment_template = TEMPLATE
        with patch("app.core.kubernetes_management.get_current_model_version", return_value=7):
            mgr.rerender_inference_deployment("det_abc", is_oodd=True)

        kwargs = mgr._app_kube_client.patch_namespaced_deployment.call_args.kwargs
        assert kwargs["name"] == get_edge_inference_deployment_name("det_abc", is_oodd=True)
        assert kwargs["namespace"] == "edge"
        [op] = kwargs["body"]
        assert op["op"] == "replace" and op["path"] == "/spec/template"
        template = op["value"]
        container = template["spec"]["containers"][0]
        assert container["image"] == "gl-edge-inference:abc123-triton"
        assert container["env"] == [{"name": "MODEL_NAME", "value": get_edge_inference_model_name("det_abc", True)}]
        assert template["metadata"]["labels"] == {"instance": "instance-det_abc-oodd"}
        annotations = template["metadata"]["annotations"]
        assert annotations["groundlight.dev/inference-server"] == "triton"
        assert annotations["groundlight.dev/model-version"] == "7"

    def test_stamps_a_restart_so_an_unchanged_template_still_rolls(self):
        """A deployment already on the configured server renders to its current template; it must still roll."""
        mgr = _make_manager()
        mgr._inference_deployment_template = TEMPLATE
        with (
            patch("app.core.kubernetes_management.get_current_model_version", return_value=7),
            patch("app.core.kubernetes_management.datetime") as dt,
        ):
            dt.now.return_value.isoformat.return_value = "2026-10-20T12:00:00"
            mgr.rerender_inference_deployment("det_abc")

        [op] = mgr._app_kube_client.patch_namespaced_deployment.call_args.kwargs["body"]
        annotations = op["value"]["metadata"]["annotations"]
        assert annotations["kubectl.kubernetes.io/restartedAt"] == "2026-10-20T12:00:00"


def _deployment(name: str, selector: dict | None) -> V1Deployment:
    return V1Deployment(
        metadata=V1ObjectMeta(name=name),
        spec=V1DeploymentSpec(selector=V1LabelSelector(match_labels=selector), template=V1PodTemplateSpec()),
    )


def _service(name: str, selector: dict | None) -> V1Service:
    return V1Service(metadata=V1ObjectMeta(name=name), spec=V1ServiceSpec(selector=selector))


INFERENCE_SELECTOR = {"app": "inference-server", "instance": "instance-det_x-primary"}


class TestListInferenceResources:
    def test_lists_only_inference_deployments(self):
        mgr = _make_manager()
        mgr._app_kube_client.list_namespaced_deployment.return_value.items = [
            _deployment("edge-endpoint", {"app": "edge-logic-server"}),
            _deployment("edge-endpoint-network-healer", {"app": "edge-endpoint-network-healer"}),
            _deployment("inferencemodel-primary-det-a", {"app": "something-else"}),
            _deployment("inferencemodel-primary-det-b", None),
            _deployment("inferencemodel-primary-det-c", INFERENCE_SELECTOR),
            _deployment("inferencemodel-oodd-det-c", INFERENCE_SELECTOR),
            _deployment("my-inferencemodel-primary-det-d", INFERENCE_SELECTOR),
        ]

        names = [d.metadata.name for d in mgr.list_inference_deployments()]

        assert names == ["inferencemodel-primary-det-c", "inferencemodel-oodd-det-c"]

    def test_lists_only_inference_services(self):
        mgr = _make_manager()
        mgr._core_kube_client.list_namespaced_service.return_value.items = [
            _service("edge-endpoint-service", {"app": "edge-logic-server"}),
            _service("inference-service-primary-det-a", None),
            _service("inference-service-primary-det-b", {"app": "something-else"}),
            _service("inference-service-primary-det-c", INFERENCE_SELECTOR),
            _service("inference-service-oodd-det-c", INFERENCE_SELECTOR),
        ]

        names = [s.metadata.name for s in mgr.list_inference_services()]

        assert names == ["inference-service-primary-det-c", "inference-service-oodd-det-c"]


class TestNamespaceScoping:
    """One edge-endpoint must never see or delete another namespace's inference pods."""

    def test_every_call_uses_the_namespace_from_the_namespace_file(self, tmp_path):
        namespace_file = tmp_path / "namespace"
        namespace_file.write_text("edge-2\n")
        with (
            patch("app.core.kubernetes_management.KUBERNETES_NAMESPACE_PATH", str(namespace_file)),
            patch("app.core.kubernetes_management.config.load_incluster_config"),
            patch("app.core.kubernetes_management.kube_client.AppsV1Api") as apps_api,
            patch("app.core.kubernetes_management.kube_client.CoreV1Api") as core_api,
            patch(
                "app.core.kubernetes_management.InferenceDeploymentManager._load_inference_deployment_template",
                return_value="",
            ),
        ):
            from app.core.kubernetes_management import InferenceDeploymentManager

            mgr = InferenceDeploymentManager()
        apps, core = apps_api.return_value, core_api.return_value

        mgr.list_inference_deployments()
        mgr.list_inference_services()
        mgr.delete_inference_resources(deployment_name="inferencemodel-primary-det-x", service_name="svc")
        mgr.delete_inference_deployment("det_x", is_oodd=True)
        mgr.inference_pods_gone("instance-det_x-primary")
        mgr.is_inference_deployment_fully_deleted("det_x")

        assert mgr.namespace == "edge-2"
        # Direct calls on the API clients, not on the objects they return.
        calls = [c for c in apps.mock_calls + core.mock_calls if c[0] and "." not in c[0] and "(" not in c[0]]
        assert calls and all(c.kwargs["namespace"] == "edge-2" for c in calls)
        assert {c[0] for c in calls} == {
            "list_namespaced_deployment",
            "list_namespaced_service",
            "list_namespaced_pod",
            "read_namespaced_deployment",
            "delete_namespaced_deployment",
            "delete_namespaced_service",
        }


class TestDeleteInferenceResources:
    def test_deletes_only_what_is_named(self):
        mgr = _make_manager()
        mgr.delete_inference_resources(service_name="inference-service-primary-det-x")

        mgr._app_kube_client.delete_namespaced_deployment.assert_not_called()
        mgr._core_kube_client.delete_namespaced_service.assert_called_once_with(
            name="inference-service-primary-det-x", namespace="edge"
        )

    def test_ignores_resources_that_are_already_gone(self):
        mgr = _make_manager()
        mgr._app_kube_client.delete_namespaced_deployment.side_effect = ApiException(status=404)
        mgr._core_kube_client.delete_namespaced_service.side_effect = ApiException(status=404)

        mgr.delete_inference_resources(deployment_name="d", service_name="s")

    def test_raises_other_errors(self):
        mgr = _make_manager()
        mgr._app_kube_client.delete_namespaced_deployment.side_effect = ApiException(status=403)

        with pytest.raises(ApiException):
            mgr.delete_inference_resources(deployment_name="d")

    def test_delete_inference_deployment_deletes_the_detectors_deployment_and_service(self):
        mgr = _make_manager()
        mgr.delete_inference_deployment("det_AbC", is_oodd=True)

        mgr._app_kube_client.delete_namespaced_deployment.assert_called_once_with(
            name="inferencemodel-oodd-det-abc", namespace="edge"
        )
        mgr._core_kube_client.delete_namespaced_service.assert_called_once_with(
            name="inference-service-oodd-det-abc", namespace="edge"
        )


class TestInferencePodsGone:
    def test_selects_inference_pods_by_instance(self):
        mgr = _make_manager()
        mgr._core_kube_client.list_namespaced_pod.return_value = _make_pod_list(0)

        assert mgr.inference_pods_gone("instance-det_AbC-primary") is True
        mgr._core_kube_client.list_namespaced_pod.assert_called_once_with(
            namespace="edge", label_selector="app=inference-server,instance=instance-det_AbC-primary"
        )

    def test_false_while_pods_remain(self):
        mgr = _make_manager()
        mgr._core_kube_client.list_namespaced_pod.return_value = _make_pod_list(1)
        assert mgr.inference_pods_gone("instance-det_x-primary") is False

    def test_fully_deleted_needs_the_deployment_and_its_pods_gone(self):
        mgr = _make_manager()
        mgr.get_inference_deployment = MagicMock(return_value=None)
        mgr._core_kube_client.list_namespaced_pod.return_value = _make_pod_list(0)

        assert mgr.is_inference_deployment_fully_deleted("det_AbC", is_oodd=True) is True
        mgr._core_kube_client.list_namespaced_pod.assert_called_once_with(
            namespace="edge", label_selector="app=inference-server,instance=instance-det_AbC-oodd"
        )
