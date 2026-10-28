from unittest.mock import MagicMock, patch


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


class TestSwitchInferenceServer:
    def test_replaces_the_pod_template_with_one_rendered_from_the_current_template(self):
        """A JSON patch replaces the whole pod template, so nothing from the old server is merged in."""
        from app.core.naming import get_edge_inference_deployment_name, get_edge_inference_model_name

        mgr = _make_manager()
        mgr._inference_deployment_template = TEMPLATE
        with patch("app.core.kubernetes_management.get_current_model_version", return_value=7):
            mgr.switch_inference_server("det_abc", is_oodd=True)

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
            mgr.switch_inference_server("det_abc")

        [op] = mgr._app_kube_client.patch_namespaced_deployment.call_args.kwargs["body"]
        annotations = op["value"]["metadata"]["annotations"]
        assert annotations["kubectl.kubernetes.io/restartedAt"] == "2026-10-20T12:00:00"
