from unittest.mock import MagicMock, patch


def _make_manager():
    """Create an InferenceDeploymentManager with mocked-out __init__."""
    with patch("app.core.kubernetes_management.InferenceDeploymentManager.__init__", return_value=None):
        from app.core.kubernetes_management import InferenceDeploymentManager

        mgr = InferenceDeploymentManager()
        mgr._db_manager = MagicMock()
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


class TestSubstitutePlaceholders:
    def test_image_placeholder_replaced(self):
        """The placeholder-inference-image string is replaced with the per-detector image URI."""
        mgr = _make_manager()
        mgr._inference_deployment_template = (
            "kind: Deployment\nspec:\n  containers:\n  - image: placeholder-inference-image\n"
        )
        out = mgr._substitute_placeholders(
            service_name="svc", deployment_name="dep", model_name="det/primary", image="ecr/full:tag"
        )
        assert "placeholder-inference-image" not in out
        assert "ecr/full:tag" in out


class TestGetDeploymentImage:
    def test_returns_inference_server_image(self):
        mgr = _make_manager()
        container = MagicMock()
        container.name = "inference-server"
        container.image = "ecr/full:tag"
        dep = MagicMock()
        dep.spec.template.spec.containers = [container]
        mgr.get_inference_deployment = MagicMock(return_value=dep)
        assert mgr.get_deployment_image("dep") == "ecr/full:tag"

    def test_returns_none_when_missing(self):
        mgr = _make_manager()
        mgr.get_inference_deployment = MagicMock(return_value=None)
        assert mgr.get_deployment_image("dep") is None
