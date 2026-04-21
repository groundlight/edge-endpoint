"""Tests for the pure-logic helpers in app/metrics/resource_metrics.py.

These cover the functions that contain real logic (parsers, filters,
attribution rules). The thin K8s-API wrappers (_get_node_ram,
_get_pod_ram_metrics, _query_pod_gpu) are exercised indirectly through their
inputs/outputs being passed into the pure helpers tested here.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from kubernetes import client

from app.metrics.resource_metrics import (
    _attribute_detector_resources,
    _find_inference_pods,
    _parse_eviction_threshold,
    _parse_k8s_memory,
    _pick_active_pods,
)

DET_A = "det_aaaaaaaaaaaaaaaaaaaaaaaaaaa"
DET_B = "det_bbbbbbbbbbbbbbbbbbbbbbbbbbb"


def _make_inference_pod(
    name: str,
    detector_id: str | None = DET_A,
    is_oodd: bool = False,
    phase: str = "Running",
    pod_ip: str | None = "10.0.0.1",
    creation_timestamp: datetime | None = None,
) -> client.V1Pod:
    """Build a MagicMock pod that looks like an inference pod to _find_inference_pods."""
    pod = MagicMock(spec=client.V1Pod)
    pod.metadata.name = name
    pod.metadata.creation_timestamp = creation_timestamp
    annotations = {}
    if detector_id is not None:
        annotations["groundlight.dev/detector-id"] = detector_id
        annotations["groundlight.dev/model-name"] = f"{detector_id}/oodd" if is_oodd else f"{detector_id}/primary"
    pod.metadata.annotations = annotations
    pod.status.phase = phase
    pod.status.pod_ip = pod_ip
    # Default to Ready=True so _pod_is_ready returns True; tests can override.
    cond = MagicMock()
    cond.type = "Ready"
    cond.status = "True"
    pod.status.conditions = [cond]
    cs = MagicMock()
    cs.name = "inference-server"
    cs.ready = True
    cs.state.waiting = None
    pod.status.container_statuses = [cs]
    return pod


def _set_not_ready(pod: client.V1Pod) -> None:
    """Mutate a pod produced by _make_inference_pod so _pod_is_ready returns False."""
    pod.status.conditions[0].status = "False"
    pod.status.container_statuses[0].ready = False


def _make_pod_list(pods: list) -> MagicMock:
    """Wrap pods in a list response object that mimics V1PodList."""
    pod_list = MagicMock()
    pod_list.items = pods
    return pod_list


class TestParseK8sMemory:
    def test_binary_suffixes(self):
        """Ki / Mi / Gi / Ti map to 1024-based powers."""
        assert _parse_k8s_memory("1Ki") == 1024
        assert _parse_k8s_memory("2Mi") == 2 * 1024**2
        assert _parse_k8s_memory("4Gi") == 4 * 1024**3
        assert _parse_k8s_memory("1Ti") == 1024**4

    def test_decimal_suffixes(self):
        """K / M / G / T map to 1000-based powers."""
        assert _parse_k8s_memory("1K") == 1000
        assert _parse_k8s_memory("3M") == 3 * 1000**2
        assert _parse_k8s_memory("2G") == 2 * 1000**3

    def test_no_suffix(self):
        """Bare integer is treated as bytes."""
        assert _parse_k8s_memory("4096") == 4096

    def test_fractional(self):
        """Fractional values like '1.5Gi' are accepted."""
        assert _parse_k8s_memory("1.5Gi") == int(1.5 * 1024**3)

    def test_unparseable_returns_zero(self):
        """Garbage input returns 0 instead of raising."""
        assert _parse_k8s_memory("not-a-number") == 0
        assert _parse_k8s_memory("") == 0


class TestParseEvictionThreshold:
    def _make_node(self, node_args: list[str] | None) -> MagicMock:
        """Build a node mock whose annotations contain the given k3s node-args."""
        node = MagicMock()
        if node_args is None:
            node.metadata.annotations = {}
        else:
            import json

            node.metadata.annotations = {"k3s.io/node-args": json.dumps(node_args)}
        return node

    def test_eviction_soft_percentage(self):
        """`memory.available<10%` yields `100 - 10 = 90`."""
        node = self._make_node(["--eviction-soft=memory.available<10%"])
        assert _parse_eviction_threshold(node) == 90

    def test_eviction_hard_used_when_no_soft(self):
        """Falls back to eviction-hard if eviction-soft isn't present."""
        node = self._make_node(["--eviction-hard=memory.available<5%"])
        assert _parse_eviction_threshold(node) == 95

    def test_absolute_form_returns_none(self):
        """Absolute thresholds (`memory.available<500Mi`) aren't supported; returns None."""
        node = self._make_node(["--eviction-soft=memory.available<500Mi"])
        assert _parse_eviction_threshold(node) is None

    def test_missing_annotation_returns_none(self):
        """Non-k3s nodes (no annotation) yield None rather than crashing."""
        assert _parse_eviction_threshold(self._make_node(None)) is None


class TestFindInferencePods:
    def test_includes_running_pod_with_annotations(self):
        """A Running pod with detector-id + model-name annotations is included."""
        pod = _make_inference_pod("pod-a", detector_id=DET_A, is_oodd=False)
        result = _find_inference_pods(_make_pod_list([pod]))
        assert len(result) == 1
        _, det_id, is_oodd, is_ready = result[0]
        assert det_id == DET_A
        assert is_oodd is False
        assert is_ready is True

    def test_excludes_pending_pod(self):
        """Pending pods are dropped even if they have an IP and the right annotations."""
        pod = _make_inference_pod("pod-pending", phase="Pending")
        assert _find_inference_pods(_make_pod_list([pod])) == []

    def test_excludes_pod_without_ip(self):
        """Running pods without a pod_ip are dropped (can't be queried for GPU)."""
        pod = _make_inference_pod("pod-no-ip", pod_ip=None)
        assert _find_inference_pods(_make_pod_list([pod])) == []

    def test_excludes_non_inference_pod(self):
        """Pods without the groundlight detector annotations are dropped."""
        pod = _make_inference_pod("some-sidecar", detector_id=None)
        assert _find_inference_pods(_make_pod_list([pod])) == []

    def test_distinguishes_oodd_from_primary(self):
        """`/oodd` model-name suffix sets is_oodd=True."""
        primary = _make_inference_pod("pod-primary", is_oodd=False)
        oodd = _make_inference_pod("pod-oodd", is_oodd=True)
        result = {tup[0].metadata.name: tup[2] for tup in _find_inference_pods(_make_pod_list([primary, oodd]))}
        assert result == {"pod-primary": False, "pod-oodd": True}


class TestPickActivePods:
    def test_newest_ready_wins(self):
        """Within a (detector_id, is_oodd) group, the newest ready pod is active."""
        old = _make_inference_pod("old", creation_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc))
        new = _make_inference_pod("new", creation_timestamp=datetime(2026, 2, 1, tzinfo=timezone.utc))
        pods = [(old, DET_A, False, True), (new, DET_A, False, True)]
        assert _pick_active_pods(pods) == {"new"}

    def test_no_active_when_none_ready(self):
        """If no pod in the group is ready, none are picked active (all go to loading)."""
        a = _make_inference_pod("a", creation_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc))
        b = _make_inference_pod("b", creation_timestamp=datetime(2026, 2, 1, tzinfo=timezone.utc))
        pods = [(a, DET_A, False, False), (b, DET_A, False, False)]
        assert _pick_active_pods(pods) == set()

    def test_separate_groups_for_primary_and_oodd(self):
        """Primary and oodd pods for the same detector are independent groups."""
        primary = _make_inference_pod("primary", creation_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc))
        oodd = _make_inference_pod("oodd", creation_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc))
        pods = [(primary, DET_A, False, True), (oodd, DET_A, True, True)]
        assert _pick_active_pods(pods) == {"primary", "oodd"}


class TestAttributeDetectorResources:
    def test_active_pod_routes_to_detector_slot(self):
        """An active pod's RAM/VRAM lands in its detector's primary or oodd slot."""
        primary = _make_inference_pod("primary-pod")
        oodd = _make_inference_pod("oodd-pod", is_oodd=True)
        inference_pods = [(primary, DET_A, False, True), (oodd, DET_A, True, True)]
        active = {"primary-pod", "oodd-pod"}
        gpu_responses = {
            "primary-pod": {"pod": {"vram_bytes": 100}},
            "oodd-pod": {"pod": {"vram_bytes": 50}},
        }
        ram_by_pod = {"primary-pod": 1000, "oodd-pod": 500}

        detectors, loading_vram, loading_ram = _attribute_detector_resources(
            inference_pods, active, gpu_responses, ram_by_pod
        )

        assert loading_vram == 0 and loading_ram == 0
        assert len(detectors) == 1
        det = detectors[0]
        assert det["detector_id"] == DET_A
        assert det["vram"] == {"primary_bytes": 100, "oodd_bytes": 50, "total_bytes": 150}
        assert det["ram"] == {"primary_bytes": 1000, "oodd_bytes": 500, "total_bytes": 1500}

    def test_inactive_pod_routes_to_loading(self):
        """A non-active pod's RAM/VRAM rolls into the loading totals, not into a detector slot."""
        active_pod = _make_inference_pod("active")
        loading_pod = _make_inference_pod("loading")
        inference_pods = [(active_pod, DET_A, False, True), (loading_pod, DET_A, False, False)]
        active = {"active"}
        gpu_responses = {
            "active": {"pod": {"vram_bytes": 100}},
            "loading": {"pod": {"vram_bytes": 800}},
        }
        ram_by_pod = {"active": 1000, "loading": 5000}

        detectors, loading_vram, loading_ram = _attribute_detector_resources(
            inference_pods, active, gpu_responses, ram_by_pod
        )

        assert loading_vram == 800 and loading_ram == 5000
        assert len(detectors) == 1
        assert detectors[0]["vram"]["primary_bytes"] == 100
        assert detectors[0]["ram"]["primary_bytes"] == 1000

    def test_missing_gpu_data_yields_zero_vram(self):
        """A pod with no GPU response contributes 0 VRAM but still picks up RAM from Metrics Server."""
        pod = _make_inference_pod("p")
        inference_pods = [(pod, DET_A, False, True)]
        detectors, _, _ = _attribute_detector_resources(inference_pods, {"p"}, gpu_responses={}, ram_by_pod={"p": 1000})
        assert detectors[0]["vram"]["primary_bytes"] == 0
        assert detectors[0]["ram"]["primary_bytes"] == 1000
