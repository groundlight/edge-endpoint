from unittest.mock import MagicMock

import pytest
from kubernetes import client

from app.metrics.system_metrics import (
    _derive_detector_status,
    _get_pod_error_reason,
    _has_progress_deadline_exceeded,
    _pod_is_ready,
)


def _make_deployment(
    replicas: int = 1,
    status_replicas: int | None = 1,
    ready_replicas: int | None = 1,
    updated_replicas: int | None = 1,
    available_replicas: int | None = 1,
    conditions: list | None = None,
) -> client.V1Deployment:
    dep = MagicMock(spec=client.V1Deployment)
    dep.spec.replicas = replicas
    dep.status.replicas = status_replicas
    dep.status.ready_replicas = ready_replicas
    dep.status.updated_replicas = updated_replicas
    dep.status.available_replicas = available_replicas
    dep.status.conditions = conditions
    return dep


def _make_pod(
    phase: str = "Running",
    ready_condition: bool = True,
    container_ready: bool = True,
    waiting_reason: str | None = None,
) -> client.V1Pod:
    pod = MagicMock(spec=client.V1Pod)
    pod.status.phase = phase

    condition = MagicMock()
    condition.type = "Ready"
    condition.status = "True" if ready_condition else "False"
    pod.status.conditions = [condition]

    cs = MagicMock()
    cs.name = "inference-server"
    cs.ready = container_ready

    if waiting_reason:
        cs.state.waiting.reason = waiting_reason
        cs.state.running = None
    else:
        cs.state.waiting = None

    pod.status.container_statuses = [cs]
    return pod


class TestPodIsReady:
    def test_ready_pod(self):
        pod = _make_pod()
        assert _pod_is_ready(pod) is True

    def test_not_running_phase(self):
        pod = _make_pod(phase="Pending")
        assert _pod_is_ready(pod) is False

    def test_no_ready_condition(self):
        pod = _make_pod(ready_condition=False)
        assert _pod_is_ready(pod) is False

    def test_container_not_ready(self):
        pod = _make_pod(container_ready=False)
        assert _pod_is_ready(pod) is False

    def test_none_pod(self):
        assert _pod_is_ready(None) is False


class TestGetPodErrorReason:
    @pytest.mark.parametrize("reason", [
        "CrashLoopBackOff",
        "ImagePullBackOff",
        "ErrImagePull",
        "CreateContainerConfigError",
    ])
    def test_error_reasons(self, reason):
        pod = _make_pod(waiting_reason=reason)
        assert _get_pod_error_reason(pod) == reason

    def test_no_error(self):
        pod = _make_pod()
        assert _get_pod_error_reason(pod) is None

    def test_non_error_waiting_reason(self):
        pod = _make_pod(waiting_reason="ContainerCreating")
        assert _get_pod_error_reason(pod) is None


class TestHasProgressDeadlineExceeded:
    def test_exceeded(self):
        condition = MagicMock()
        condition.type = "Progressing"
        condition.status = "False"
        condition.reason = "ProgressDeadlineExceeded"
        dep = _make_deployment(conditions=[condition])
        assert _has_progress_deadline_exceeded(dep) is True

    def test_not_exceeded(self):
        condition = MagicMock()
        condition.type = "Progressing"
        condition.status = "True"
        condition.reason = "NewReplicaSetAvailable"
        dep = _make_deployment(conditions=[condition])
        assert _has_progress_deadline_exceeded(dep) is False

    def test_no_conditions(self):
        dep = _make_deployment(conditions=None)
        assert _has_progress_deadline_exceeded(dep) is False


class TestDeriveDetectorStatus:
    def test_ready(self):
        dep = _make_deployment(replicas=1, status_replicas=1, ready_replicas=1, updated_replicas=1, available_replicas=1)
        status, detail = _derive_detector_status(dep, [])
        assert status == "ready"
        assert detail is None

    def test_updating_surge_pod(self):
        """Rolling update: old pod available, new pod starting (total > desired)."""
        dep = _make_deployment(replicas=1, status_replicas=2, ready_replicas=1, updated_replicas=1, available_replicas=1)
        status, detail = _derive_detector_status(dep, [])
        assert status == "updating"
        assert detail is None

    def test_updating_not_yet_updated(self):
        """Rolling update: available pod exists but updated count is behind."""
        dep = _make_deployment(replicas=1, status_replicas=1, ready_replicas=1, updated_replicas=0, available_replicas=1)
        status, detail = _derive_detector_status(dep, [])
        assert status == "updating"
        assert detail is None

    def test_initializing_no_pods(self):
        dep = _make_deployment(replicas=1, status_replicas=1, ready_replicas=0, updated_replicas=1, available_replicas=0)
        pod = _make_pod(phase="Pending", ready_condition=False, container_ready=False)
        # No error reason on pod
        pod.status.container_statuses[0].state.waiting = None
        status, detail = _derive_detector_status(dep, [pod])
        assert status == "initializing"
        assert detail is None

    def test_initializing_no_pods_at_all(self):
        dep = _make_deployment(replicas=1, status_replicas=0, ready_replicas=0, updated_replicas=0, available_replicas=0)
        status, detail = _derive_detector_status(dep, [])
        assert status == "initializing"
        assert detail is None

    def test_error_crash_loop(self):
        dep = _make_deployment(replicas=1, status_replicas=1, ready_replicas=0, updated_replicas=1, available_replicas=0)
        pod = _make_pod(waiting_reason="CrashLoopBackOff", ready_condition=False, container_ready=False)
        status, detail = _derive_detector_status(dep, [pod])
        assert status == "error"
        assert detail == "CrashLoopBackOff"

    def test_error_image_pull(self):
        dep = _make_deployment(replicas=1, status_replicas=1, ready_replicas=0, updated_replicas=1, available_replicas=0)
        pod = _make_pod(waiting_reason="ImagePullBackOff", ready_condition=False, container_ready=False)
        status, detail = _derive_detector_status(dep, [pod])
        assert status == "error"
        assert detail == "ImagePullBackOff"

    def test_error_progress_deadline_exceeded(self):
        condition = MagicMock()
        condition.type = "Progressing"
        condition.status = "False"
        condition.reason = "ProgressDeadlineExceeded"
        dep = _make_deployment(
            replicas=1, status_replicas=1, ready_replicas=1, updated_replicas=0,
            available_replicas=1, conditions=[condition],
        )
        status, detail = _derive_detector_status(dep, [])
        assert status == "error"
        assert detail == "ProgressDeadlineExceeded"
