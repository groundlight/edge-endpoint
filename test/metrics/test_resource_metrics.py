"""Tests for the pure-logic helpers in app/metrics/resource_metrics.py.

These cover the functions that contain real logic (parsers, filters,
attribution rules).
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from kubernetes import client

from app.metrics.resource_metrics import (
    TRITON_GPU_METRICS_MAX_AGE_SEC,
    _attribute_detector_resources,
    _build_gpu_summary,
    _find_inference_pods,
    _get_node_resources,
    _parse_eviction_threshold,
    _parse_k8s_cpu,
    _parse_k8s_memory,
    _parse_triton_gpu_metrics,
    _pick_active_pods,
    _query_pod_gpu,
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
    drop_model_name: bool = False,
) -> client.V1Pod:
    """Build a MagicMock pod that looks like an inference pod to _find_inference_pods.

    Defaults satisfy `_pod_is_ready` (Running + Ready condition + container ready).
    `drop_model_name=True` keeps detector-id but omits model-name to exercise the
    half-annotated branch in `_find_inference_pods`.
    """
    pod = MagicMock(spec=client.V1Pod)
    pod.metadata.name = name
    pod.metadata.creation_timestamp = creation_timestamp
    annotations = {}
    if detector_id is not None:
        annotations["groundlight.dev/detector-id"] = detector_id
        if not drop_model_name:
            annotations["groundlight.dev/model-name"] = f"{detector_id}/oodd" if is_oodd else f"{detector_id}/primary"
    pod.metadata.annotations = annotations
    pod.status.phase = phase
    pod.status.pod_ip = pod_ip
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


def _make_node(node_args: list[str] | None) -> MagicMock:
    """Build a node mock whose annotations contain the given k3s node-args."""
    node = MagicMock()
    if node_args is None:
        node.metadata.annotations = {}
    else:
        node.metadata.annotations = {"k3s.io/node-args": json.dumps(node_args)}
    return node


def _gpu_device(
    name: str = "NVIDIA A10",
    index: int = 0,
    total: int = 1000,
    used: int = 100,
    free: int = 900,
    uuid: str | None = "GPU-uuid-0",
    compute_pct: float = 0.0,
    memory_bw_pct: float = 0.0,
) -> dict:
    """Build a single device entry as it appears in the /v2/gpu-usage response."""
    return {
        "name": name,
        "index": index,
        "vram_total_bytes": total,
        "vram_used_bytes": used,
        "vram_free_bytes": free,
        "uuid": uuid,
        "compute_utilization_pct": compute_pct,
        "memory_bandwidth_pct": memory_bw_pct,
    }


def _gpu_process(vram: int, compute_pct: float = 0.0, memory_bw_pct: float = 0.0) -> dict:
    """Build a process entry as it appears in the /v2/gpu-usage response."""
    return {
        "process": {
            "vram_used_bytes": vram,
            "compute_utilization_pct": compute_pct,
            "memory_bandwidth_pct": memory_bw_pct,
        }
    }


class TestParseK8sMemory:
    def test_binary_suffixes(self):
        """Ki / Mi / Gi / Ti map to 1024-based powers."""
        assert _parse_k8s_memory("1Ki") == 1024
        assert _parse_k8s_memory("2Mi") == 2 * 1024**2
        assert _parse_k8s_memory("4Gi") == 4 * 1024**3
        assert _parse_k8s_memory("1Ti") == 1024**4

    def test_decimal_suffixes(self):
        """K / M / G map to 1000-based powers."""
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


class TestParseK8sCpu:
    def test_cores(self):
        """Bare CPU values are cores and convert to millicores."""
        assert _parse_k8s_cpu("2") == 2000.0
        assert _parse_k8s_cpu("1.5") == 1500.0

    def test_millicores(self):
        """The `m` suffix is already in millicores."""
        assert _parse_k8s_cpu("250m") == 250.0

    def test_micro_and_nanocores(self):
        """Metrics Server sub-millicore quantities are converted without truncation."""
        assert _parse_k8s_cpu("1000u") == 1.0
        assert _parse_k8s_cpu("1000000n") == 1.0

    def test_unparseable_returns_zero(self):
        """Garbage input returns 0 instead of raising."""
        assert _parse_k8s_cpu("not-a-number") == 0.0
        assert _parse_k8s_cpu("") == 0.0


class TestParseEvictionThreshold:
    def test_eviction_soft_percentage(self):
        """`memory.available<10%` yields `100 - 10 = 90`."""
        node = _make_node(["--eviction-soft=memory.available<10%"])
        assert _parse_eviction_threshold(node) == 90

    def test_eviction_hard_used_when_no_soft(self):
        """Falls back to eviction-hard if eviction-soft isn't present."""
        node = _make_node(["--eviction-hard=memory.available<5%"])
        assert _parse_eviction_threshold(node) == 95

    def test_falls_back_to_hard_when_soft_is_absolute(self):
        """If soft is in unsupported absolute form, the hard percentage is used instead."""
        node = _make_node(["--eviction-soft=memory.available<500Mi", "--eviction-hard=memory.available<5%"])
        assert _parse_eviction_threshold(node) == 95

    def test_soft_preferred_over_hard(self):
        """When both soft and hard are present, soft wins."""
        node = _make_node(["--eviction-soft=memory.available<10%", "--eviction-hard=memory.available<5%"])
        assert _parse_eviction_threshold(node) == 90

    def test_absolute_form_returns_none(self):
        """Absolute thresholds (`memory.available<500Mi`) aren't supported; returns None."""
        node = _make_node(["--eviction-soft=memory.available<500Mi"])
        assert _parse_eviction_threshold(node) is None

    def test_missing_annotation_returns_none(self):
        """Non-k3s nodes (no annotation) yield None rather than crashing."""
        assert _parse_eviction_threshold(_make_node(None)) is None


class TestGetNodeResources:
    def test_cpu_utilization_uses_capacity_denominator(self, monkeypatch):
        """Node CPU utilization is computed from Metrics Server usage over node capacity."""
        monkeypatch.setenv("NODE_NAME", "edge-node")
        node = _make_node(None)
        node.metadata.name = "edge-node"
        node.status.capacity = {"memory": "4Gi", "cpu": "4"}
        v1 = MagicMock()
        v1.read_node.return_value = node
        node_metrics = {
            "items": [
                {
                    "metadata": {"name": "edge-node"},
                    "usage": {"memory": "2Gi", "cpu": "1000m"},
                }
            ]
        }

        with patch("app.metrics.resource_metrics.client.CustomObjectsApi") as custom_api:
            custom_api.return_value.list_cluster_custom_object.return_value = node_metrics
            result = _get_node_resources(v1)

        assert result["ram"]["total"] == 4 * 1024**3
        assert result["ram"]["used"] == 2 * 1024**3
        assert result["cpu"] == {
            "utilization_pct": 25.0,
            "used_millicores": 1000.0,
            "total_millicores": 4000.0,
        }


class TestFindInferencePods:
    def test_includes_running_pod_with_annotations(self):
        """A Running pod with detector-id + model-name annotations is included; tuple shape is (pod, det_id, is_oodd, is_ready)."""
        pod = _make_inference_pod("pod-a", detector_id=DET_A, is_oodd=False)
        result = _find_inference_pods(MagicMock(items=[pod]))
        assert len(result) == 1
        out_pod, det_id, is_oodd, is_ready = result[0]
        assert out_pod is pod
        assert det_id == DET_A
        assert is_oodd is False
        assert is_ready is True

    def test_excludes_pending_pod(self):
        """Pending pods are dropped even if they have an IP and the right annotations."""
        pod = _make_inference_pod("pod-pending", phase="Pending")
        assert _find_inference_pods(MagicMock(items=[pod])) == []

    def test_excludes_pod_without_ip(self):
        """Running pods without a pod_ip are dropped (can't be queried for GPU)."""
        pod = _make_inference_pod("pod-no-ip", pod_ip=None)
        assert _find_inference_pods(MagicMock(items=[pod])) == []

    def test_excludes_non_inference_pod(self):
        """Pods without the groundlight detector annotations are dropped."""
        pod = _make_inference_pod("some-sidecar", detector_id=None)
        assert _find_inference_pods(MagicMock(items=[pod])) == []

    def test_excludes_half_annotated_pod(self):
        """A pod with detector-id but no model-name is dropped (both annotations required)."""
        pod = _make_inference_pod("pod-half", drop_model_name=True)
        assert _find_inference_pods(MagicMock(items=[pod])) == []

    def test_distinguishes_oodd_from_primary(self):
        """`/oodd` model-name suffix sets is_oodd=True."""
        primary = _make_inference_pod("pod-primary", is_oodd=False)
        oodd = _make_inference_pod("pod-oodd", is_oodd=True)
        result = {tup[0].metadata.name: tup[2] for tup in _find_inference_pods(MagicMock(items=[primary, oodd]))}
        assert result == {"pod-primary": False, "pod-oodd": True}

    def test_includes_running_but_not_ready_pod_with_is_ready_false(self):
        """A Running pod whose container isn't ready is still returned, with is_ready=False.

        Downstream (_pick_active_pods, _attribute_detector_resources) relies on
        this to treat a paging-in replacement pod as 'loading' rather than
        dropping it from accounting entirely.
        """
        pod = _make_inference_pod("pod-loading")
        pod.status.conditions[0].status = "False"
        pod.status.container_statuses[0].ready = False
        result = _find_inference_pods(MagicMock(items=[pod]))
        assert len(result) == 1
        assert result[0][3] is False


class TestPickActivePods:
    def test_newest_ready_wins(self):
        """Within a (detector_id, is_oodd) group, the newest ready pod is active."""
        old = _make_inference_pod("old", creation_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc))
        new = _make_inference_pod("new", creation_timestamp=datetime(2026, 2, 1, tzinfo=timezone.utc))
        pods = [(old, DET_A, False, True), (new, DET_A, False, True)]
        assert _pick_active_pods(pods) == {"new"}

    def test_old_ready_pod_stays_active_during_rollout(self):
        """Rolling update: a newer not-ready pod must NOT displace the older ready pod.

        This is the core invariant that keeps the donut chart stable while a
        replacement inference pod is paging in its model weights.
        """
        old_ready = _make_inference_pod("old", creation_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc))
        new_loading = _make_inference_pod("new", creation_timestamp=datetime(2026, 2, 1, tzinfo=timezone.utc))
        pods = [(old_ready, DET_A, False, True), (new_loading, DET_A, False, False)]
        assert _pick_active_pods(pods) == {"old"}

    def test_no_active_when_none_ready(self):
        """If no pod in the group is ready, none are picked active (all go to loading)."""
        a = _make_inference_pod("a", creation_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc))
        b = _make_inference_pod("b", creation_timestamp=datetime(2026, 2, 1, tzinfo=timezone.utc))
        pods = [(a, DET_A, False, False), (b, DET_A, False, False)]
        assert _pick_active_pods(pods) == set()

    def test_groups_keyed_by_detector_and_kind(self):
        """The grouping key is (detector_id, is_oodd): different detectors and primary/oodd are independent."""
        a_primary = _make_inference_pod("a-primary", creation_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc))
        a_oodd = _make_inference_pod("a-oodd", creation_timestamp=datetime(2026, 1, 2, tzinfo=timezone.utc))
        b_primary = _make_inference_pod("b-primary", creation_timestamp=datetime(2026, 1, 3, tzinfo=timezone.utc))
        pods = [
            (a_primary, DET_A, False, True),
            (a_oodd, DET_A, True, True),
            (b_primary, DET_B, False, True),
        ]
        assert _pick_active_pods(pods) == {"a-primary", "a-oodd", "b-primary"}


class TestAttributeDetectorResources:
    def test_active_pod_routes_to_detector_slot(self):
        """An active pod's RAM/VRAM lands in its detector's primary or OODD slot, and totals sum both."""
        primary = _make_inference_pod("primary-pod")
        oodd = _make_inference_pod("oodd-pod", is_oodd=True)
        detectors, loading_vram, loading_ram, loading_gpu_compute, loading_gpu_memory, loading_cpu = (
            _attribute_detector_resources(
                inference_pods=[(primary, DET_A, False, True), (oodd, DET_A, True, True)],
                active_pods={"primary-pod", "oodd-pod"},
                gpu_responses={
                    "primary-pod": _gpu_process(100, compute_pct=10, memory_bw_pct=8),
                    "oodd-pod": _gpu_process(50, compute_pct=5, memory_bw_pct=3),
                },
                pod_resources={
                    "primary-pod": {"ram_bytes": 1000, "cpu_millicores": 100},
                    "oodd-pod": {"ram_bytes": 500, "cpu_millicores": 50},
                },
                total_cpu_millicores=1000,
            )
        )

        assert loading_vram == 0 and loading_ram == 0
        assert loading_gpu_compute == 0.0 and loading_gpu_memory == 0.0
        assert loading_cpu == 0.0
        assert len(detectors) == 1
        det = detectors[0]
        assert det["detector_id"] == DET_A
        assert det["cpu_utilization_pct"] == {"primary": 10.0, "oodd": 5.0, "total": 15.0}
        assert det["gpu"]["vram_bytes"] == {"primary": 100, "oodd": 50, "total": 150}
        assert det["ram_bytes"] == {"primary": 1000, "oodd": 500, "total": 1500}
        assert det["gpu"] == {
            "vram_bytes": {"primary": 100, "oodd": 50, "total": 150},
            "compute_utilization_pct": {"primary": 10.0, "oodd": 5.0, "total": 15.0},
            "memory_bandwidth_pct": {"primary": 8.0, "oodd": 3.0, "total": 11.0},
        }

    def test_only_primary_leaves_oodd_slot_none(self):
        """A detector with only a primary pod has oodd_bytes=None and total_bytes equal to primary."""
        primary = _make_inference_pod("primary-pod")
        inference_pods = [(primary, DET_A, False, True)]
        detectors, _, _, _, _, _ = _attribute_detector_resources(
            inference_pods,
            active_pods={"primary-pod"},
            gpu_responses={"primary-pod": _gpu_process(100)},
            pod_resources={"primary-pod": {"ram_bytes": 1000, "cpu_millicores": 0}},
            total_cpu_millicores=1000,
        )
        assert detectors[0]["gpu"]["vram_bytes"] == {"primary": 100, "oodd": None, "total": 100}
        assert detectors[0]["ram_bytes"] == {"primary": 1000, "oodd": None, "total": 1000}

    def test_multiple_detectors_produce_separate_entries(self):
        """Pods belonging to different detectors get their own entries in the output."""
        a = _make_inference_pod("a")
        b = _make_inference_pod("b")
        inference_pods = [(a, DET_A, False, True), (b, DET_B, False, True)]
        detectors, _, _, _, _, _ = _attribute_detector_resources(
            inference_pods,
            active_pods={"a", "b"},
            gpu_responses={"a": _gpu_process(100), "b": _gpu_process(200)},
            pod_resources={
                "a": {"ram_bytes": 1000, "cpu_millicores": 0},
                "b": {"ram_bytes": 2000, "cpu_millicores": 0},
            },
            total_cpu_millicores=1000,
        )
        by_id = {d["detector_id"]: d for d in detectors}
        assert set(by_id) == {DET_A, DET_B}
        assert by_id[DET_A]["gpu"]["vram_bytes"]["total"] == 100
        assert by_id[DET_B]["gpu"]["vram_bytes"]["total"] == 200

    def test_inactive_pod_routes_to_loading(self):
        """A non-active pod's RAM/VRAM rolls into the loading totals, not into a detector slot."""
        active_pod = _make_inference_pod("active")
        loading_pod = _make_inference_pod("loading")
        detectors, loading_vram, loading_ram, loading_gpu_compute, loading_gpu_memory, loading_cpu = (
            _attribute_detector_resources(
                inference_pods=[(active_pod, DET_A, False, True), (loading_pod, DET_A, False, False)],
                active_pods={"active"},
                gpu_responses={
                    "active": _gpu_process(100),
                    "loading": _gpu_process(800, compute_pct=30, memory_bw_pct=12),
                },
                pod_resources={
                    "active": {"ram_bytes": 1000, "cpu_millicores": 100},
                    "loading": {"ram_bytes": 5000, "cpu_millicores": 250},
                },
                total_cpu_millicores=1000,
            )
        )

        assert loading_vram == 800 and loading_ram == 5000
        assert loading_gpu_compute == 30.0 and loading_gpu_memory == 12.0
        assert loading_cpu == 250.0
        assert len(detectors) == 1
        assert detectors[0]["gpu"]["vram_bytes"]["primary"] == 100
        assert detectors[0]["ram_bytes"]["primary"] == 1000

    def test_missing_gpu_data_yields_zero_vram(self):
        """A pod with no GPU response contributes 0 VRAM but still picks up RAM from Metrics Server."""
        pod = _make_inference_pod("p")
        detectors, _, _, _, _, _ = _attribute_detector_resources(
            inference_pods=[(pod, DET_A, False, True)],
            active_pods={"p"},
            gpu_responses={},
            pod_resources={"p": {"ram_bytes": 1000, "cpu_millicores": 0}},
            total_cpu_millicores=1000,
        )
        assert detectors[0]["gpu"]["vram_bytes"]["primary"] == 0
        assert detectors[0]["ram_bytes"]["primary"] == 1000


class TestBuildGpuSummary:
    def test_single_pod_single_gpu(self):
        """Happy path: one pod, one device, totals match the device."""
        responses = {"pod-a": {"devices": [_gpu_device(used=200, compute_pct=20, memory_bw_pct=10)]}}
        devices, total, used, compute_pct, memory_bw_pct = _build_gpu_summary(responses)
        assert total == 1000 and used == 200
        assert devices[0]["vram_bytes"]["used"] == 200
        assert compute_pct == 20.0 and memory_bw_pct == 10.0

    def test_two_pods_same_gpu_dedupes_by_uuid(self):
        """Two pods reporting the same GPU (by uuid) must NOT double-count totals."""
        responses = {
            "pod-a": {"devices": [_gpu_device(used=200, uuid="GPU-shared", compute_pct=20)]},
            "pod-b": {"devices": [_gpu_device(used=300, uuid="GPU-shared", compute_pct=30)]},
        }
        devices, total, used, compute_pct, _ = _build_gpu_summary(responses)
        assert total == 1000 and used == 300
        assert len(devices) == 1
        assert devices[0]["vram_bytes"]["used"] == 300
        assert devices[0]["vram_bytes"]["free"] == 700
        assert devices[0]["compute_utilization_pct"] == 30.0
        assert compute_pct == 30.0

    def test_staggered_triton_readings_use_the_most_recent(self):
        """Triton pods' readings are taken at different moments; the latest one wins, not the highest."""
        responses = {
            "pod-a": {"devices": [_gpu_device(used=300, compute_pct=90, memory_bw_pct=40)], "sampled_at": 100.2},
            "pod-b": {"devices": [_gpu_device(used=200, compute_pct=30, memory_bw_pct=10)], "sampled_at": 100.9},
            "pod-c": {"devices": [_gpu_device(used=200, compute_pct=60, memory_bw_pct=20)], "sampled_at": 100.5},
        }
        devices, total, used, compute_pct, memory_bw_pct = _build_gpu_summary(responses)
        assert compute_pct == 30.0 and memory_bw_pct == 10.0
        assert used == 300 and devices[0]["vram_bytes"]["used"] == 300

    def test_current_readings_win_over_published_ones(self):
        """A FastAPI pod's reading is taken at query time, so it beats a Triton pod's published reading."""
        responses = {
            "pod-triton": {"devices": [_gpu_device(compute_pct=80)], "sampled_at": 100.9},
            "pod-fastapi": {"devices": [_gpu_device(compute_pct=20)]},
        }
        _, _, _, compute_pct, _ = _build_gpu_summary(responses)
        assert compute_pct == 20.0

    def test_dedupe_falls_back_to_name_index_when_uuid_missing(self):
        """When uuid is absent, the (name, index) pair is used as the dedupe key."""
        responses = {
            "pod-a": {"devices": [_gpu_device(used=200, uuid=None)]},
            "pod-b": {"devices": [_gpu_device(used=300, uuid=None)]},
        }
        devices, total, used, _, _ = _build_gpu_summary(responses)
        assert total == 1000 and used == 300
        assert len(devices) == 1

    def test_multiple_distinct_gpus_sorted_by_index(self):
        """Different GPUs (different uuids) are kept separate and sorted by index."""
        responses = {
            "pod-a": {
                "devices": [
                    _gpu_device(name="GPU-1", index=1, total=1000, used=100, uuid="uuid-1", compute_pct=20),
                    _gpu_device(name="GPU-0", index=0, total=2000, used=200, uuid="uuid-0", compute_pct=40),
                ]
            }
        }
        devices, total, used, compute_pct, _ = _build_gpu_summary(responses)
        assert [g["index"] for g in devices] == [0, 1]
        assert total == 3000 and used == 300
        assert compute_pct == 30.0

    def test_none_response_is_skipped(self):
        """A pod whose /v2/gpu-usage call failed (None response) is skipped without affecting totals."""
        responses = {
            "pod-down": None,
            "pod-up": {"devices": [_gpu_device(used=200)]},
        }
        devices, total, used, _, _ = _build_gpu_summary(responses)
        assert total == 1000 and used == 200
        assert len(devices) == 1

    def test_unnamed_device_excluded_from_observed_but_still_counted_in_totals(self):
        """A device with no `name` is dropped from devices but its bytes still flow into pod totals.

        Pinning current behavior so a future refactor doesn't silently change it.
        """
        responses = {
            "pod-a": {
                "devices": [
                    _gpu_device(name=None, total=500, used=50, uuid=None),
                    _gpu_device(name="NVIDIA A10", index=0, total=1000, used=200, uuid="uuid-0"),
                ]
            }
        }
        devices, total, used, _, _ = _build_gpu_summary(responses)
        assert [g["name"] for g in devices] == ["NVIDIA A10"]
        assert total == 1500 and used == 250


TRITON_METRICS = """# HELP gl_process_vram_used_bytes VRAM used by this inference process
# TYPE gl_process_vram_used_bytes gauge
gl_process_vram_used_bytes 249561088
gl_process_gpu_index 1
gl_process_gpu_compute_utilization_pct 12.5
gl_process_gpu_memory_bandwidth_pct 3
gl_gpu_vram_total_bytes{gpu_index="1",gpu_name="Tesla T4",gpu_uuid="GPU-b"} 16106127360
gl_gpu_vram_used_bytes{gpu_index="1",gpu_name="Tesla T4",gpu_uuid="GPU-b"} 718536704
gl_gpu_vram_free_bytes{gpu_index="1",gpu_name="Tesla T4",gpu_uuid="GPU-b"} 15387590656
gl_gpu_compute_utilization_pct{gpu_index="1",gpu_name="Tesla T4",gpu_uuid="GPU-b"} 40
gl_gpu_memory_bandwidth_pct{gpu_index="1",gpu_name="Tesla T4",gpu_uuid="GPU-b"} 5
gl_gpu_vram_total_bytes{gpu_index="0",gpu_name="Tesla T4",gpu_uuid="GPU-a"} 16106127360
gl_gpu_vram_used_bytes{gpu_index="0",gpu_name="Tesla T4",gpu_uuid="GPU-a"} 0
gl_gpu_vram_free_bytes{gpu_index="0",gpu_name="Tesla T4",gpu_uuid="GPU-a"} 16106127360
gl_gpu_compute_utilization_pct{gpu_index="0",gpu_name="Tesla T4",gpu_uuid="GPU-a"} 0
gl_gpu_memory_bandwidth_pct{gpu_index="0",gpu_name="Tesla T4",gpu_uuid="GPU-a"} 0
gl_gpu_usage_last_update_timestamp_seconds 1000.5
nv_inference_request_success{model="edge_model",version="1"} 7
"""


class TestParseTritonGpuMetrics:
    def test_rebuilds_the_v2_gpu_usage_payload(self):
        payload = _parse_triton_gpu_metrics(TRITON_METRICS, now=1001.0)

        assert payload == {
            "schema_version": 2,
            "process": {
                "vram_used_bytes": 249561088,
                "gpu_index": 1,
                "compute_utilization_pct": 12.5,
                "memory_bandwidth_pct": 3.0,
            },
            "devices": [
                {
                    "index": 0,
                    "uuid": "GPU-a",
                    "name": "Tesla T4",
                    "vram_total_bytes": 16106127360,
                    "vram_used_bytes": 0,
                    "vram_free_bytes": 16106127360,
                    "compute_utilization_pct": 0.0,
                    "memory_bandwidth_pct": 0.0,
                },
                {
                    "index": 1,
                    "uuid": "GPU-b",
                    "name": "Tesla T4",
                    "vram_total_bytes": 16106127360,
                    "vram_used_bytes": 718536704,
                    "vram_free_bytes": 15387590656,
                    "compute_utilization_pct": 40.0,
                    "memory_bandwidth_pct": 5.0,
                },
            ],
            "sampled_at": 1000.5,
        }

    def test_stale_gauges_are_treated_as_missing(self):
        assert _parse_triton_gpu_metrics(TRITON_METRICS, now=1000.5 + TRITON_GPU_METRICS_MAX_AGE_SEC + 1) is None

    def test_missing_process_gauges_are_treated_as_missing(self):
        text = "\n".join(line for line in TRITON_METRICS.splitlines() if not line.startswith("gl_process_vram"))
        assert _parse_triton_gpu_metrics(text, now=1001.0) is None

    def test_cpu_pods_report_no_devices(self):
        text = "\n".join(line for line in TRITON_METRICS.splitlines() if not line.startswith("gl_gpu_v"))
        text = "\n".join(line for line in text.splitlines() if not line.startswith(("gl_gpu_compute", "gl_gpu_memory")))
        payload = _parse_triton_gpu_metrics(text, now=1001.0)
        assert payload is not None
        assert payload["devices"] == []


class TestQueryPodGpu:
    def test_triton_pods_are_read_from_their_metrics_port(self):
        pod = _make_inference_pod("inferencemodel-primary-a", pod_ip="10.0.0.7")
        pod.metadata.annotations["groundlight.dev/inference-server"] = "triton"
        resp = MagicMock(text=TRITON_METRICS)
        with (
            patch("app.metrics.resource_metrics.requests.get", return_value=resp) as get,
            patch("app.metrics.resource_metrics.time.time", return_value=1001.0),
        ):
            payload = _query_pod_gpu(pod)

        get.assert_called_once_with("http://10.0.0.7:8002/metrics", timeout=2)
        assert payload["process"]["vram_used_bytes"] == 249561088

    def test_unparseable_triton_gauges_are_treated_as_missing(self):
        """One pod's bad gauges must not fail the whole collection."""
        pod = _make_inference_pod("inferencemodel-primary-a", pod_ip="10.0.0.7")
        pod.metadata.annotations["groundlight.dev/inference-server"] = "triton"
        bad_values = TRITON_METRICS.replace("gl_process_vram_used_bytes 249561088", "gl_process_vram_used_bytes NaN")
        missing_label = TRITON_METRICS.replace('gpu_name="Tesla T4",', "")
        for text in (bad_values, missing_label):
            with (
                patch("app.metrics.resource_metrics.requests.get", return_value=MagicMock(text=text)),
                patch("app.metrics.resource_metrics.time.time", return_value=1001.0),
            ):
                assert _query_pod_gpu(pod) is None

    def test_other_pods_are_read_from_v2_gpu_usage(self):
        pod = _make_inference_pod("inferencemodel-primary-a", pod_ip="10.0.0.7")
        resp = MagicMock()
        resp.json.return_value = {"schema_version": 2}
        with patch("app.metrics.resource_metrics.requests.get", return_value=resp) as get:
            assert _query_pod_gpu(pod) == {"schema_version": 2}

        get.assert_called_once_with("http://10.0.0.7:8000/v2/gpu-usage", timeout=2)
