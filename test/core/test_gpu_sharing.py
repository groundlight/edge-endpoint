import pytest

from app.core.gpu_sharing import GpuSharing, configured_gpu_sharing


def test_configured_gpu_sharing_defaults_to_none(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GPU_SHARING", raising=False)
    assert configured_gpu_sharing() is GpuSharing.NONE


def test_configured_gpu_sharing_reads_the_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GPU_SHARING", "mps")
    assert configured_gpu_sharing() is GpuSharing.MPS


def test_configured_gpu_sharing_rejects_unknown_values(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GPU_SHARING", "mig")
    with pytest.raises(ValueError):
        configured_gpu_sharing()
