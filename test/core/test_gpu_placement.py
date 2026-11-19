import pytest

from app.core.gpu_placement import GpuPlacement, configured_gpu_placement


def test_configured_gpu_placement_defaults_to_none(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GPU_PLACEMENT", raising=False)
    assert configured_gpu_placement() is GpuPlacement.NONE


def test_configured_gpu_placement_reads_the_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GPU_PLACEMENT", "ledger")
    assert configured_gpu_placement() is GpuPlacement.LEDGER


def test_configured_gpu_placement_rejects_unknown_values(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GPU_PLACEMENT", "binpack")
    with pytest.raises(ValueError):
        configured_gpu_placement()
