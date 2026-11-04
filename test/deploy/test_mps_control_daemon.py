"""Tests for the chart's MPS daemon supervisor (deploy/helm/groundlight-edge-endpoint/files/mps_control_daemon.py)."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "deploy/helm/groundlight-edge-endpoint/files/mps_control_daemon.py"


@pytest.fixture
def daemon(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The supervisor module, loaded fresh with its pipe directory in tmp_path."""
    monkeypatch.setenv("CUDA_MPS_PIPE_DIRECTORY", str(tmp_path))
    spec = importlib.util.spec_from_file_location("mps_control_daemon", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_binaries_lists_what_the_runtime_did_not_inject(daemon, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(daemon.shutil, "which", lambda name: None if name == "nvidia-cuda-mps-server" else "/usr/bin/x")

    assert daemon.missing_binaries() == ["nvidia-cuda-mps-server"]


def test_without_the_binaries_the_daemon_reports_unavailable_and_idles(daemon, monkeypatch, tmp_path: Path):
    monkeypatch.setattr(daemon.shutil, "which", lambda name: None)
    seen = {}

    def stop_immediately() -> None:
        seen["marker"] = (tmp_path / "gl-unavailable").read_text()

    monkeypatch.setattr(daemon, "wait_for_stop", stop_immediately)

    def popen(*args, **kwargs):
        raise AssertionError("must not start nvidia-cuda-mps-control")

    monkeypatch.setattr(daemon.subprocess, "Popen", popen)
    (tmp_path / "gl-ready").touch()  # left over from a daemon that was killed

    assert daemon.run_daemon() == 0
    assert "nvidia-cuda-mps-control and nvidia-cuda-mps-server not found" in seen["marker"]
    assert not (tmp_path / "gl-ready").exists()
    assert not (tmp_path / "gl-unavailable").exists()  # removed again when the daemon stops


def test_with_the_binaries_a_stale_unavailable_marker_and_sockets_are_removed(daemon, monkeypatch, tmp_path: Path):
    monkeypatch.setattr(daemon.shutil, "which", lambda name: f"/usr/bin/{name}")
    for name in ("gl-unavailable", "control", "control_privileged"):
        (tmp_path / name).touch()

    def popen(*args, **kwargs):
        raise RuntimeError("daemon started")

    monkeypatch.setattr(daemon.subprocess, "Popen", popen)

    with pytest.raises(RuntimeError, match="daemon started"):
        daemon.run_daemon()
    assert not any((tmp_path / name).exists() for name in ("gl-unavailable", "control", "control_privileged"))
