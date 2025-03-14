from app.metrics.metricreporting import SafeMetricsDict, _metrics_payload


def test_metrics_payload():
    payload = _metrics_payload()
    assert "device_id" in payload
    assert "now" in payload
    assert isinstance(payload["cpucores"], int)


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
