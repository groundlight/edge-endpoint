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
        """Returns False when the deployment doesn't exist."""
        mgr = _make_manager()
        mgr.get_inference_deployment = MagicMock(return_value=None)
        assert mgr.is_inference_deployment_rollout_complete("test-dep") is False

    def test_replicas_not_yet_updated(self):
        """Returns False during a rollout when replicas haven't converged yet.
        Should not even check for terminating pods in this case."""
        mgr = _make_manager()
        mgr.get_inference_deployment = MagicMock(
            return_value=_make_deployment(replicas=1, updated=0, available=0, total=1)
        )
        assert mgr.is_inference_deployment_rollout_complete("test-dep") is False
        mgr._core_kube_client.list_namespaced_pod.assert_not_called()

    def test_complete_when_replicas_match_and_no_extra_pods(self):
        """Returns True when replica counts match and no terminating pods linger."""
        mgr = _make_manager()
        mgr.get_inference_deployment = MagicMock(return_value=_make_deployment())
        mgr._core_kube_client.list_namespaced_pod.return_value = _make_pod_list(1)
        assert mgr.is_inference_deployment_rollout_complete("test-dep") is True

    def test_incomplete_when_terminating_pod_lingers(self):
        """Returns False when replica counts look healthy but a terminating pod
        still exists (e.g. old pod hasn't released GPU memory yet)."""
        mgr = _make_manager()
        mgr.get_inference_deployment = MagicMock(return_value=_make_deployment())
        mgr._core_kube_client.list_namespaced_pod.return_value = _make_pod_list(2)
        assert mgr.is_inference_deployment_rollout_complete("test-dep") is False

    def test_complete_with_multiple_replicas(self):
        """Returns True for a multi-replica deployment with no extras."""
        mgr = _make_manager()
        mgr.get_inference_deployment = MagicMock(
            return_value=_make_deployment(replicas=3, updated=3, available=3, total=3)
        )
        mgr._core_kube_client.list_namespaced_pod.return_value = _make_pod_list(3)
        assert mgr.is_inference_deployment_rollout_complete("test-dep") is True

    def test_scale_down_with_lingering_pods(self):
        """Returns False after scaling from 3 to 1 when old pods are still terminating."""
        mgr = _make_manager()
        mgr.get_inference_deployment = MagicMock(
            return_value=_make_deployment(replicas=1, updated=1, available=1, total=1)
        )
        mgr._core_kube_client.list_namespaced_pod.return_value = _make_pod_list(3)
        assert mgr.is_inference_deployment_rollout_complete("test-dep") is False
