import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.metrics.metric_reporting import MetricsReporter, SafeMetricsDict


def _deliberate_error():
    raise RuntimeError("Intentional test error")


def _fake_payload(activity_hour: str, num_iqs: int = 100) -> dict:
    """A minimal report payload with a controllable activity_hour and per-detector count."""
    return {
        "device_info": {"device_id": "device_test", "now": "2026-06-24T16:00:00"},
        "activity_metrics": {
            "activity_hour": activity_hour,
            "detector_activity_previous_hour": json.dumps({"det_1": {"hourly_total_iqs": num_iqs}}),
        },
        "k3s_stats": {},
    }


def _reported_iqs(payload: dict) -> int:
    """Pull det_1's hourly_total_iqs out of a (fake) payload."""
    return json.loads(payload["activity_metrics"]["detector_activity_previous_hour"])["det_1"]["hourly_total_iqs"]


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


class TestMetricsReporter:
    """Test suite for the MetricsReporter class."""

    def _check_payload_structure(self, payload):
        # Check that the three top-level keys exist
        assert "device_info" in payload
        assert isinstance(payload["device_info"], dict)
        assert "activity_metrics" in payload
        assert isinstance(payload["activity_metrics"], dict)
        assert "k3s_stats" in payload
        assert isinstance(payload["k3s_stats"], dict)

        # Check that the payload dictionaries have all the expected keys
        device_info = payload["device_info"]
        assert "device_id" in device_info
        assert "device_metadata" in device_info
        assert "now" in device_info
        assert "cpucores" in device_info
        assert "inference_flavor" in device_info
        assert "cpu_utilization" in device_info
        assert "memory_utilization" in device_info
        assert "memory_available_bytes" in device_info

        activity_metrics = payload["activity_metrics"]
        assert "last_activity_time" in activity_metrics
        assert "activity_hour" in activity_metrics
        assert "num_detectors_lifetime" in activity_metrics
        assert "num_detectors_active_1h" in activity_metrics
        assert "num_detectors_active_24h" in activity_metrics
        assert "detector_activity_previous_hour" in activity_metrics

        k3s_stats = payload["k3s_stats"]
        assert "deployments" in k3s_stats
        assert "pod_statuses" in k3s_stats
        assert "container_images" in k3s_stats

        # Check that the full payload is JSON serializable
        json.dumps(payload)

    def _get_mock_api_client(self, status_code=200):
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.headers = {"Authorization": "Bearer fake-token"}
        mock_api_client = MagicMock()
        mock_api_client.call_api.return_value = (None, mock_response.status_code, mock_response.headers)
        return mock_api_client

    def test_metrics_payload(self):
        reporter = MetricsReporter()
        payload = reporter.metrics_payload()
        self._check_payload_structure(payload)

    def test_collect_metrics_for_cloud(self, tmp_path):
        """Metrics are collected and sealed once per hour (re-collecting the same hour is idempotent)."""
        reporter = MetricsReporter(pending_reports_dir=tmp_path)

        reporter.collect_metrics_for_cloud()
        assert len(reporter.metrics_to_send) == 1

        # Collecting again within the same hour is a no-op (first-writer-wins).
        reporter.collect_metrics_for_cloud()
        assert len(reporter.metrics_to_send) == 1

        _, payload = next(iter(reporter.metrics_to_send.items()))
        self._check_payload_structure(payload)

    def test_collect_is_idempotent_per_hour(self, tmp_path):
        """Two collections for the same hour keep the first sealed snapshot, even if the second read
        would have produced different counts. This is the edge-side guard against the cloud's
        "same key, different value" rejection."""
        reporter = MetricsReporter(pending_reports_dir=tmp_path)

        with patch.object(reporter, "metrics_payload", return_value=_fake_payload("2026-06-24_15", num_iqs=100)):
            reporter.collect_metrics_for_cloud()
        with patch.object(reporter, "metrics_payload", return_value=_fake_payload("2026-06-24_15", num_iqs=200)):
            reporter.collect_metrics_for_cloud()

        assert list(reporter.metrics_to_send) == ["2026-06-24_15"]
        # The first snapshot is kept; the drifted re-read is ignored.
        assert _reported_iqs(reporter.metrics_to_send["2026-06-24_15"]) == 100
        assert (tmp_path / "2026-06-24_15.json").exists()

    def test_pending_report_persisted_and_reloaded_after_restart(self, tmp_path):
        """A queued snapshot survives a restart, and re-collecting that hour afterward stays deduped."""
        reporter = MetricsReporter(pending_reports_dir=tmp_path)
        with patch.object(reporter, "metrics_payload", return_value=_fake_payload("2026-06-24_15", num_iqs=100)):
            reporter.collect_metrics_for_cloud()

        # Simulate a restart: a brand-new reporter starts empty, then reloads from disk.
        restarted = MetricsReporter(pending_reports_dir=tmp_path)
        assert restarted.metrics_to_send == {}
        restarted.load_pending_reports()
        assert "2026-06-24_15" in restarted.metrics_to_send

        # Re-collecting the same hour after a reload won't replace it with a freshly-read value.
        with patch.object(restarted, "metrics_payload", return_value=_fake_payload("2026-06-24_15", num_iqs=999)):
            restarted.collect_metrics_for_cloud()
        assert len(restarted.metrics_to_send) == 1
        assert _reported_iqs(restarted.metrics_to_send["2026-06-24_15"]) == 100

    @patch("app.metrics.metric_reporting._groundlight_client")
    def test_successful_send_removes_persisted_report(self, mock_gl_client, tmp_path):
        """A 200 response clears the snapshot from memory and disk."""
        mock_gl_client.return_value.api_client = self._get_mock_api_client(status_code=200)
        reporter = MetricsReporter(pending_reports_dir=tmp_path)
        with patch.object(reporter, "metrics_payload", return_value=_fake_payload("2026-06-24_15")):
            reporter.collect_metrics_for_cloud()
        assert (tmp_path / "2026-06-24_15.json").exists()

        reporter.report_metrics_to_cloud()

        assert reporter.metrics_to_send == {}
        assert not (tmp_path / "2026-06-24_15.json").exists()

    @patch("app.metrics.metric_reporting._groundlight_client")
    def test_failed_send_keeps_persisted_report(self, mock_gl_client, tmp_path):
        """A non-200 response keeps the snapshot queued (in memory and on disk) for a later retry."""
        mock_gl_client.return_value.api_client = self._get_mock_api_client(status_code=400)
        reporter = MetricsReporter(pending_reports_dir=tmp_path)
        with patch.object(reporter, "metrics_payload", return_value=_fake_payload("2026-06-24_15")):
            reporter.collect_metrics_for_cloud()

        reporter.report_metrics_to_cloud()

        assert "2026-06-24_15" in reporter.metrics_to_send
        assert (tmp_path / "2026-06-24_15.json").exists()

    def test_prune_drops_only_stale_reports(self, tmp_path):
        """Reports older than the max age are dropped; fresh ones are retained."""
        reporter = MetricsReporter(pending_reports_dir=tmp_path)
        stale_hour = (datetime.now(timezone.utc) - timedelta(days=8)).strftime("%Y-%m-%d_%H")
        fresh_hour = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%d_%H")
        for hour in (stale_hour, fresh_hour):
            payload = _fake_payload(hour)
            reporter._persist_report(hour, payload)
            reporter.metrics_to_send[hour] = payload

        reporter._prune_stale_reports()

        assert stale_hour not in reporter.metrics_to_send
        assert not (tmp_path / f"{stale_hour}.json").exists()
        assert fresh_hour in reporter.metrics_to_send
        assert (tmp_path / f"{fresh_hour}.json").exists()

    @patch("app.metrics.metric_reporting._groundlight_client")
    def test_report_single_metric_payload_to_cloud(self, mock_gl_client):
        """Test that a single metric payload is reported correctly."""
        mock_api_client = self._get_mock_api_client()
        mock_gl_client.return_value.api_client = mock_api_client

        reporter = MetricsReporter()
        reporter.metrics_to_send = {"timestamp": {"payload": "payload"}}
        reporter.report_metrics_to_cloud()

        # Verify the API was called
        mock_api_client.call_api.assert_called_once()

        assert len(reporter.metrics_to_send) == 0

    @patch("app.metrics.metric_reporting._groundlight_client")
    def test_report_multiple_metric_payloads_to_cloud(self, mock_gl_client):
        """Test that multiple metric payloads are reported correctly."""
        mock_api_client = self._get_mock_api_client()
        mock_gl_client.return_value.api_client = mock_api_client

        reporter = MetricsReporter()
        reporter.metrics_to_send = {
            "timestamp1": {"payload": "payload1"},
            "timestamp2": {"payload": "payload2"},
            "timestamp3": {"payload": "payload3"},
        }
        reporter.report_metrics_to_cloud()

        # Verify the API was called and metrics_to_send was cleared
        assert mock_api_client.call_api.call_count == 3
        assert len(reporter.metrics_to_send) == 0

    @patch("app.metrics.metric_reporting._groundlight_client")
    def test_report_metric_payload_to_cloud_failure(self, mock_gl_client):
        """Test that a metric payload is kept in metrics_to_send if the cloud API call fails."""
        mock_api_client = self._get_mock_api_client(status_code=400)
        mock_gl_client.return_value.api_client = mock_api_client

        reporter = MetricsReporter()
        mock_metrics = {
            "timestamp1": {"payload": "payload1"},
            "timestamp2": {"payload": "payload2"},
            "timestamp3": {"payload": "payload3"},
        }
        reporter.metrics_to_send = mock_metrics.copy()
        reporter.report_metrics_to_cloud()

        # Verify the API was called and metrics_to_send was not cleared
        assert mock_api_client.call_api.call_count == 3
        assert len(reporter.metrics_to_send) == 3
        assert reporter.metrics_to_send == mock_metrics

    @patch("app.metrics.metric_reporting._groundlight_client")
    def test_report_metric_payload_empty_metrics_to_send(self, mock_gl_client):
        """Test that a metric payload is kept in metrics_to_send if the cloud API call fails."""
        mock_api_client = self._get_mock_api_client(status_code=400)
        mock_gl_client.return_value.api_client = mock_api_client

        reporter = MetricsReporter()
        reporter.metrics_to_send = {}
        reporter.report_metrics_to_cloud()

        assert mock_api_client.call_api.call_count == 0
        assert len(reporter.metrics_to_send) == 0
