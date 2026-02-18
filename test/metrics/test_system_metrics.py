from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from kubernetes import client

from app.metrics.system_metrics import (
    _derive_detector_status,
    _get_pod_error_reason,
    _pod_is_progressing,
    _pod_is_ready,
)


def _make_deployment(
    replicas: int = 1,
    status_replicas: int | None = 1,
    ready_replicas: int | None = 1,
    updated_replicas: int | None = 1,
    available_replicas: int | None = 1,
) -> client.V1Deployment:
    dep = MagicMock(spec=client.V1Deployment)
    dep.spec.replicas = replicas
    dep.status.replicas = status_replicas
    dep.status.ready_replicas = ready_replicas
    dep.status.updated_replicas = updated_replicas
    dep.status.available_replicas = available_replicas
    return dep


def _make_pod(
    phase: str = "Running",
    ready_condition: bool = True,
    container_ready: bool = True,
    waiting_reason: str | None = None,
    creation_timestamp: datetime | None = None,
) -> client.V1Pod:
    pod = MagicMock(spec=client.V1Pod)
    pod.status.phase = phase
    pod.metadata.creation_timestamp = creation_timestamp

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
    @pytest.mark.parametrize(
        "reason",
        [
            "CrashLoopBackOff",
            "ImagePullBackOff",
            "ErrImagePull",
            "CreateContainerConfigError",
        ],
    )
    def test_error_reasons(self, reason):
        pod = _make_pod(waiting_reason=reason)
        assert _get_pod_error_reason(pod) == reason

    def test_no_error(self):
        pod = _make_pod()
        assert _get_pod_error_reason(pod) is None

    def test_non_error_waiting_reason(self):
        pod = _make_pod(waiting_reason="ContainerCreating")
        assert _get_pod_error_reason(pod) is None


class TestPodIsProgressing:
    def test_container_creating(self):
        pod = _make_pod(waiting_reason="ContainerCreating", ready_condition=False, container_ready=False)
        assert _pod_is_progressing(pod) is True

    def test_pod_initializing(self):
        pod = _make_pod(waiting_reason="PodInitializing", ready_condition=False, container_ready=False)
        assert _pod_is_progressing(pod) is True

    def test_running_not_ready(self):
        pod = _make_pod(phase="Running", ready_condition=False, container_ready=False)
        pod.status.container_statuses[0].state.waiting = None
        assert _pod_is_progressing(pod) is True

    def test_pending_no_container_statuses(self):
        """Freshly created pod with no container statuses yet."""
        pod = _make_pod(phase="Pending", ready_condition=False, container_ready=False)
        pod.status.container_statuses = []
        assert _pod_is_progressing(pod) is True

    def test_image_pull_backoff_is_not_progressing(self):
        pod = _make_pod(phase="Pending", waiting_reason="ImagePullBackOff", ready_condition=False, container_ready=False)
        assert _pod_is_progressing(pod) is False

    def test_crash_loop_is_not_progressing(self):
        pod = _make_pod(waiting_reason="CrashLoopBackOff", ready_condition=False, container_ready=False)
        assert _pod_is_progressing(pod) is False


class TestDeriveDetectorStatus:
    def test_ready(self):
        dep = _make_deployment(
            replicas=1, status_replicas=1, ready_replicas=1, updated_replicas=1, available_replicas=1
        )
        status, detail = _derive_detector_status(dep, [])
        assert status == "ready"
        assert detail is None

    def test_updating_new_pod_creating_container(self):
        """Rolling update: new pod is actively creating its container."""
        dep = _make_deployment(
            replicas=1, status_replicas=2, ready_replicas=1, updated_replicas=1, available_replicas=1
        )
        new_pod = _make_pod(waiting_reason="ContainerCreating", ready_condition=False, container_ready=False)
        status, detail = _derive_detector_status(dep, [new_pod])
        assert status == "updating"
        assert detail is None

    def test_updating_new_pod_running_not_ready(self):
        """Rolling update: new pod is running but hasn't passed readiness probes yet."""
        dep = _make_deployment(
            replicas=1, status_replicas=2, ready_replicas=1, updated_replicas=1, available_replicas=1
        )
        new_pod = _make_pod(phase="Running", ready_condition=False, container_ready=False)
        new_pod.status.container_statuses[0].state.waiting = None
        status, detail = _derive_detector_status(dep, [new_pod])
        assert status == "updating"
        assert detail is None

    def test_updating_new_pod_pending(self):
        """Rolling update: new pod is pending with no container statuses yet."""
        dep = _make_deployment(
            replicas=1, status_replicas=2, ready_replicas=1, updated_replicas=1, available_replicas=1
        )
        new_pod = _make_pod(phase="Pending", ready_condition=False, container_ready=False)
        new_pod.status.container_statuses = []
        status, detail = _derive_detector_status(dep, [new_pod])
        assert status == "updating"
        assert detail is None

    def test_ready_when_new_pod_is_failing(self):
        """Old pod still serving, new pod stuck in error -- report ready, not updating."""
        dep = _make_deployment(
            replicas=1, status_replicas=2, ready_replicas=1, updated_replicas=0, available_replicas=1
        )
        failing_pod = _make_pod(waiting_reason="CrashLoopBackOff", ready_condition=False, container_ready=False)
        status, detail = _derive_detector_status(dep, [failing_pod])
        assert status == "ready"
        assert detail is None

    def test_ready_when_new_pod_has_image_pull_error(self):
        """Old pod still serving, new pod stuck in ErrImagePull -- report ready."""
        dep = _make_deployment(
            replicas=1, status_replicas=2, ready_replicas=1, updated_replicas=0, available_replicas=1
        )
        failing_pod = _make_pod(waiting_reason="ErrImagePull", ready_condition=False, container_ready=False)
        status, detail = _derive_detector_status(dep, [failing_pod])
        assert status == "ready"
        assert detail is None

    def test_initializing_pod_starting(self):
        dep = _make_deployment(
            replicas=1, status_replicas=1, ready_replicas=0, updated_replicas=1, available_replicas=0
        )
        pod = _make_pod(phase="Pending", ready_condition=False, container_ready=False)
        pod.status.container_statuses[0].state.waiting = None
        status, detail = _derive_detector_status(dep, [pod])
        assert status == "initializing"
        assert detail is None

    def test_initializing_no_pods_at_all(self):
        dep = _make_deployment(
            replicas=1, status_replicas=0, ready_replicas=0, updated_replicas=0, available_replicas=0
        )
        status, detail = _derive_detector_status(dep, [])
        assert status == "initializing"
        assert detail is None

    def test_error_crash_loop(self):
        dep = _make_deployment(
            replicas=1, status_replicas=1, ready_replicas=0, updated_replicas=1, available_replicas=0
        )
        pod = _make_pod(waiting_reason="CrashLoopBackOff", ready_condition=False, container_ready=False)
        status, detail = _derive_detector_status(dep, [pod])
        assert status == "error"
        assert detail == "CrashLoopBackOff"

    def test_error_image_pull(self):
        dep = _make_deployment(
            replicas=1, status_replicas=1, ready_replicas=0, updated_replicas=1, available_replicas=0
        )
        pod = _make_pod(waiting_reason="ImagePullBackOff", ready_condition=False, container_ready=False)
        status, detail = _derive_detector_status(dep, [pod])
        assert status == "error"
        assert detail == "ImagePullBackOff"

    def test_error_uses_newest_pod(self):
        """When multiple pods are failing, use the error from the newest one."""
        dep = _make_deployment(
            replicas=1, status_replicas=2, ready_replicas=0, updated_replicas=0, available_replicas=0
        )
        old_pod = _make_pod(
            waiting_reason="ImagePullBackOff",
            ready_condition=False,
            container_ready=False,
            creation_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        new_pod = _make_pod(
            waiting_reason="CrashLoopBackOff",
            ready_condition=False,
            container_ready=False,
            creation_timestamp=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )
        status, detail = _derive_detector_status(dep, [old_pod, new_pod])
        assert status == "error"
        assert detail == "CrashLoopBackOff"
