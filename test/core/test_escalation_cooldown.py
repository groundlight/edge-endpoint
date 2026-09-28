import multiprocessing
import time

from groundlight.edge import EdgeEndpointConfig, InferenceConfig

from app.core.edge_inference import EdgeInferenceManager
from app.core.escalation_cooldown import reserve_escalation_if_cooldown_elapsed

DET_A = "det_AAAAAAAAAAAAAAAAAAAAAAAAAAA"
DET_B = "det_BBBBBBBBBBBBBBBBBBBBBBBBBBB"


def _config(detector_id: str, min_interval_sec: float) -> EdgeEndpointConfig:
    """Edge config whose only detector uses the given escalation interval."""
    config = EdgeEndpointConfig()
    config.add_detector(
        detector_id,
        InferenceConfig(name="limited", min_time_between_escalations=min_interval_sec),
    )
    return config


def _reserve_when_released(directory: str, detector_id: str, start, results) -> None:
    """Reserve one escalation after the parent releases every racer together."""
    start.wait(10)
    results.put(reserve_escalation_if_cooldown_elapsed(detector_id, 60.0, directory=directory))


def test_separate_managers_share_one_escalation_cooldown(tmp_path, monkeypatch):
    """Two worker processes must honor one interval, not one interval each."""
    monkeypatch.setattr("app.core.file_paths.ESCALATION_COOLDOWN_DIR", str(tmp_path))
    clock = {"now": 1_000.0}
    monkeypatch.setattr(time, "time", lambda: clock["now"])
    config = _config(DET_A, min_interval_sec=5.0)

    first = EdgeInferenceManager()
    second = EdgeInferenceManager()

    assert first.try_reserve_escalation(DET_A, config) is True
    clock["now"] = 1_004.0
    assert second.try_reserve_escalation(DET_A, config) is False
    clock["now"] = 1_005.1
    assert second.try_reserve_escalation(DET_A, config) is True


def test_detectors_do_not_share_a_cooldown(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1_000.0)
    assert reserve_escalation_if_cooldown_elapsed(DET_A, 5.0, directory=str(tmp_path)) is True
    assert reserve_escalation_if_cooldown_elapsed(DET_B, 5.0, directory=str(tmp_path)) is True


def test_unexpected_detector_id_is_not_used_as_a_path(tmp_path):
    assert reserve_escalation_if_cooldown_elapsed("../not-a-detector", 5.0, directory=str(tmp_path)) is False
    assert not list(tmp_path.iterdir())


def test_unreadable_timestamp_does_not_stick(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1_000.0)
    (tmp_path / DET_A).write_text("not-a-time\n")
    assert reserve_escalation_if_cooldown_elapsed(DET_A, 5.0, directory=str(tmp_path)) is True
    assert (tmp_path / DET_A).read_text().startswith("1000.")


def test_reserve_returns_false_when_the_clock_cannot_be_saved(tmp_path, monkeypatch):
    def _boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("app.core.escalation_cooldown.os.makedirs", _boom)
    assert reserve_escalation_if_cooldown_elapsed(DET_A, 5.0, directory=str(tmp_path)) is False


def test_concurrent_reserves_allow_one_escalation(tmp_path):
    """Eight processes racing the same detector get a single reservation."""
    ctx = multiprocessing.get_context("fork")
    start = ctx.Event()
    results = ctx.Queue()
    procs = [ctx.Process(target=_reserve_when_released, args=(str(tmp_path), DET_A, start, results)) for _ in range(8)]
    for proc in procs:
        proc.start()
    start.set()
    for proc in procs:
        proc.join(10)
        assert proc.exitcode == 0
    assert sum(results.get(timeout=5) for _ in procs) == 1
