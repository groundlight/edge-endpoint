
from app.metrics.metricreporting import _metrics_payload

def test_metrics_payload():
    payload = _metrics_payload()
    assert "device_id" in payload
    assert "now" in payload
    assert isinstance(payload["cpucores"], int)
