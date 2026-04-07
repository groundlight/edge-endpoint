import json
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.profiling.manager import ProfilingManager
from app.profiling.middleware import ProfilingMiddleware, _parse_detector_id


@pytest.fixture
def profiling_app():
    """Create a minimal FastAPI app with the profiling middleware."""
    test_app = FastAPI()
    test_app.add_middleware(ProfilingMiddleware)

    @test_app.get("/test")
    async def test_endpoint(detector_id: str = "det_test"):
        return {"status": "ok"}

    return test_app


@pytest.fixture
def tmp_manager(tmp_path):
    """ProfilingManager writing to a temp directory."""
    return ProfilingManager(base_dir=str(tmp_path / "profiling"))


class TestProfilingMiddleware:
    def test_no_traces_when_disabled(self, profiling_app):
        """When ENABLE_PROFILING is not set, no traces should be created."""
        with TestClient(profiling_app) as client:
            response = client.get("/test?detector_id=det_1")
            assert response.status_code == 200

    def test_traces_created_when_enabled(self, profiling_app, tmp_manager):
        """When profiling is enabled, traces should be written for each request."""
        with (
            patch("app.profiling.middleware.PROFILING_ENABLED", True),
            patch("app.profiling.get_profiling_manager", return_value=tmp_manager),
        ):
            with TestClient(profiling_app) as client:
                response = client.get("/test?detector_id=det_1")
                assert response.status_code == 200

        trace_files = list(tmp_manager.traces_dir.glob("traces_*.jsonl"))
        assert len(trace_files) >= 1

        with open(trace_files[0]) as f:
            trace = json.loads(f.readline())
            assert trace["detector_id"] == "det_1"
            assert len(trace["spans"]) >= 1
            assert trace["spans"][0]["name"] == "request"

    def test_multiple_requests_traced(self, profiling_app, tmp_manager):
        """Multiple requests should produce multiple traces."""
        with (
            patch("app.profiling.middleware.PROFILING_ENABLED", True),
            patch("app.profiling.get_profiling_manager", return_value=tmp_manager),
        ):
            with TestClient(profiling_app) as client:
                for i in range(3):
                    response = client.get(f"/test?detector_id=det_{i}")
                    assert response.status_code == 200

        trace_files = list(tmp_manager.traces_dir.glob("traces_*.jsonl"))
        total_lines = 0
        for f in trace_files:
            with open(f) as fh:
                total_lines += sum(1 for _ in fh)
        assert total_lines == 3

    def test_unknown_detector_id(self, profiling_app, tmp_manager):
        """Requests without detector_id should use 'unknown'."""
        with (
            patch("app.profiling.middleware.PROFILING_ENABLED", True),
            patch("app.profiling.get_profiling_manager", return_value=tmp_manager),
        ):
            with TestClient(profiling_app) as client:
                response = client.get("/test")
                assert response.status_code == 200

        trace_files = list(tmp_manager.traces_dir.glob("traces_*.jsonl"))
        with open(trace_files[0]) as f:
            trace = json.loads(f.readline())
            assert trace["detector_id"] == "unknown"


class TestParseDetectorId:
    def test_extracts_detector_id(self):
        assert _parse_detector_id("detector_id=det_123&foo=bar") == "det_123"

    def test_detector_id_at_end(self):
        assert _parse_detector_id("foo=bar&detector_id=det_456") == "det_456"

    def test_missing_detector_id(self):
        assert _parse_detector_id("foo=bar") == "unknown"

    def test_empty_query_string(self):
        assert _parse_detector_id("") == "unknown"
