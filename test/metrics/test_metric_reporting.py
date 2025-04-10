import json

from app.metrics.metric_reporting import SafeMetricsDict, metrics_payload


def test_metrics_payload():
    payload = metrics_payload()

    # Check that the three top-level keys exist
    assert "device_info" in payload
    assert isinstance(payload["device_info"], dict)
    assert "activity_metrics" in payload
    assert isinstance(payload["activity_metrics"], dict)
    assert "k8s_stats" in payload
    assert isinstance(payload["k8s_stats"], dict)

    # Check that the payload dictionaries have all the expected keys
    device_info = payload["device_info"]
    assert "device_id" in device_info
    assert "device_metadata" in device_info
    assert "now" in device_info
    assert "cpucores" in device_info
    assert "inference_flavor" in device_info
    assert "cpu_usage_pct" in device_info
    assert "memory_used_pct" in device_info
    assert "memory_available_bytes" in device_info

    activity_metrics = payload["activity_metrics"]
    assert "last_image_processed" in activity_metrics
    assert "num_detectors_lifetime" in activity_metrics
    assert "num_detectors_active_1h" in activity_metrics
    assert "num_detectors_active_24h" in activity_metrics
    assert "detector_activity" in activity_metrics

    k8s_stats = payload["k8s_stats"]
    assert "deployments" in k8s_stats
    assert "pod_statuses" in k8s_stats
    assert "container_images" in k8s_stats

    # Check that the full payload is JSON serializable
    json.dumps(payload)


def _deliberate_error():
    raise RuntimeError("Intentional test error")


class TestSafeMetricsDict:
    """Test suite for the SafeMetricsDict class."""

    def test_add_successful_metric(self):
        """Test that a successful metric gets added correctly."""
        metrics = SafeMetricsDict()
        metrics.add("test_key", lambda: "test_value")

        assert metrics.data == {"test_key": "test_value"}
        assert metrics.as_dict() == {"test_key": "test_value"}

    def test_add_exception_handling(self):
        """Test that exceptions in metric functions are handled properly."""
        metrics = SafeMetricsDict()

        def failing_function():
            raise ValueError("Test error")

        metrics.add("error_key", failing_function)

        assert "error_key" in metrics.data
        assert "error" in metrics.data["error_key"]
        assert "Test error" in metrics.data["error_key"]["error"]

    def test_multiple_metrics(self):
        """Test adding multiple metrics, including a mix of successful and failing ones."""
        metrics = SafeMetricsDict()

        metrics.add("key1", lambda: 42)
        metrics.add("key2", lambda: {"nested": "value"})
        metrics.add("key3", lambda: _deliberate_error())

        result = metrics.as_dict()

        assert result["key1"] == 42
        assert result["key2"] == {"nested": "value"}
        assert "error" in result["key3"]

    def test_non_serializable_value(self):
        """Test that non-JSON-serializable values are caught."""
        metrics = SafeMetricsDict()

        set_data = {1, 2, 3}  # python set is not JSON serializable
        metrics.add("bad_json", lambda: set_data)

        assert "error" in metrics.data["bad_json"]
        assert "JSON" in metrics.data["bad_json"]["error"]
