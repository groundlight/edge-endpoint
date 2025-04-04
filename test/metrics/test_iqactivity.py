from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from app.metrics.iqactivity import FilesystemActivityTrackingHelper, clear_old_activity_files, record_activity


@pytest.fixture(scope="module")
def tmp_base_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("base_dir")


@pytest.fixture(scope="module")
def _test_tracker(tmp_base_dir):
    tracker = FilesystemActivityTrackingHelper(tmp_base_dir)
    yield tracker


def test_initial_directories(tmp_base_dir, _test_tracker):
    # Check that basic directories exist after we create the tracker
    assert Path(tmp_base_dir).exists()
    assert Path(tmp_base_dir, "detectors").exists()


def test_increment_counter_file(tmp_base_dir, _test_tracker):
    assert not Path(tmp_base_dir, "increment_test").exists()
    _test_tracker.increment_counter_file("increment_test")
    assert Path(tmp_base_dir, "increment_test").exists()
    assert Path(tmp_base_dir, "increment_test").read_text() == "1"
    _test_tracker.increment_counter_file("increment_test")
    assert Path(tmp_base_dir, "increment_test").read_text() == "2"

    assert not Path(tmp_base_dir, "detectors", "det_incrementtest", "increment_test").exists()
    _test_tracker.increment_counter_file("increment_test", "det_incrementtest")
    assert Path(tmp_base_dir, "detectors", "det_incrementtest", "increment_test").exists()
    assert Path(tmp_base_dir, "detectors", "det_incrementtest", "increment_test").read_text() == "1"
    _test_tracker.increment_counter_file("increment_test", "det_incrementtest")
    assert Path(tmp_base_dir, "detectors", "det_incrementtest", "increment_test").read_text() == "2"


def test_activity_tracking(monkeypatch, tmp_base_dir, _test_tracker):
    monkeypatch.setattr("app.metrics.iqactivity._tracker", lambda: _test_tracker)
    assert not Path(tmp_base_dir, "detectors", "det_recordactivitytest").exists()

    # Record an IQ, check that the last_iq file, iqs file, and detector-specific iqs file are all
    # created and have the correct values
    with patch("app.metrics.iqactivity.datetime") as mock_datetime:
        mock_datetime.now.return_value = datetime(2025, 4, 3, 12, 0, 0)
        record_activity("det_recordactivitytest", "iqs")
        assert Path(tmp_base_dir, "detectors", "det_recordactivitytest", "iqs").exists()
        assert Path(tmp_base_dir, "detectors", "det_recordactivitytest", "iqs").read_text() == "1"
        assert Path(tmp_base_dir, "detectors", "det_recordactivitytest", "iqs_2025-04-03_12").exists()
        assert Path(tmp_base_dir, "detectors", "det_recordactivitytest", "iqs_2025-04-03_12").read_text() == "1"
        assert Path(tmp_base_dir, "last_iq").exists()
        assert Path(tmp_base_dir, "iqs").exists()
        assert Path(tmp_base_dir, "iqs").read_text() == "1"
        assert Path(tmp_base_dir, "iqs_2025-04-03_12").exists()
        assert Path(tmp_base_dir, "iqs_2025-04-03_12").read_text() == "1"

        # Record another IQ, make sure all files are updated correctly
        mock_datetime.now.return_value = datetime(2025, 4, 3, 12, 0, 1)
        record_activity("det_recordactivitytest", "iqs")
        assert Path(tmp_base_dir, "detectors", "det_recordactivitytest", "iqs").read_text() == "2"
        assert Path(tmp_base_dir, "detectors", "det_recordactivitytest", "iqs_2025-04-03_12").read_text() == "2"
        assert Path(tmp_base_dir, "iqs").read_text() == "2"
        assert Path(tmp_base_dir, "detectors", "det_recordactivitytest", "iqs").read_text() == "2"
        assert Path(tmp_base_dir, "iqs_2025-04-03_12").read_text() == "2"

        # Record an escalation and an audit, make sure the detector-specific files are created and have
        # the correct values
        record_activity("det_recordactivitytest", "escalations")
        assert Path(tmp_base_dir, "detectors", "det_recordactivitytest", "escalations").exists()
        assert Path(tmp_base_dir, "detectors", "det_recordactivitytest", "escalations").read_text() == "1"
        assert Path(tmp_base_dir, "detectors", "det_recordactivitytest", "escalations_2025-04-03_12").exists()
        assert Path(tmp_base_dir, "detectors", "det_recordactivitytest", "escalations_2025-04-03_12").read_text() == "1"
        record_activity("det_recordactivitytest", "audits")
        assert Path(tmp_base_dir, "detectors", "det_recordactivitytest", "audits").exists()
        assert Path(tmp_base_dir, "detectors", "det_recordactivitytest", "audits").read_text() == "1"
        assert Path(tmp_base_dir, "detectors", "det_recordactivitytest", "audits_2025-04-03_12").exists()
        assert Path(tmp_base_dir, "detectors", "det_recordactivitytest", "audits_2025-04-03_12").read_text() == "1"


def test_wrong_activity_type(caplog):
    record_activity("det_123", "wrong_activity_type")
    assert "The provided activity type (wrong_activity_type) is not currently supported" in caplog.text


def test_clear_old_activity_files(monkeypatch, tmp_base_dir, _test_tracker):
    monkeypatch.setattr("app.metrics.iqactivity._tracker", lambda: _test_tracker)
    Path(tmp_base_dir, "detectors", "det_123").mkdir(parents=True)
    Path(tmp_base_dir, "detectors", "det_456").mkdir(parents=True)

    # Create base files
    Path(tmp_base_dir, "iqs").touch()
    Path(tmp_base_dir, "iqs_2025-04-03_08").touch()
    Path(tmp_base_dir, "iqs_2025-04-03_09").touch()
    Path(tmp_base_dir, "iqs_2025-04-03_10").touch()
    Path(tmp_base_dir, "iqs_2025-04-03_11").touch()
    Path(tmp_base_dir, "iqs_2025-04-03_12").touch()

    # Create files for det_123
    Path(tmp_base_dir, "detectors", "det_123", "iqs").touch()
    Path(tmp_base_dir, "detectors", "det_123", "escalations").touch()
    Path(tmp_base_dir, "detectors", "det_123", "audits").touch()
    Path(tmp_base_dir, "detectors", "det_123", "iqs_2025-04-03_08").touch()
    Path(tmp_base_dir, "detectors", "det_123", "iqs_2025-04-03_09").touch()
    Path(tmp_base_dir, "detectors", "det_123", "iqs_2025-04-03_10").touch()
    Path(tmp_base_dir, "detectors", "det_123", "iqs_2025-04-03_11").touch()
    Path(tmp_base_dir, "detectors", "det_123", "iqs_2025-04-03_12").touch()
    Path(tmp_base_dir, "detectors", "det_123", "escalations_2025-04-03_12").touch()
    Path(tmp_base_dir, "detectors", "det_123", "audits_2025-04-03_12").touch()

    # Create files for det_456
    Path(tmp_base_dir, "detectors", "det_456", "iqs").touch()
    Path(tmp_base_dir, "detectors", "det_456", "escalations").touch()
    Path(tmp_base_dir, "detectors", "det_456", "iqs_2010-04-03_09").touch()

    with patch("app.metrics.iqactivity.datetime") as mock_datetime:
        mock_datetime.now.return_value = datetime(2025, 4, 3, 12, 30, 0)
        clear_old_activity_files()

    # All totals files created should be kept
    assert Path(tmp_base_dir, "iqs").exists()
    assert Path(tmp_base_dir, "detectors", "det_123", "iqs").exists()
    assert Path(tmp_base_dir, "detectors", "det_123", "escalations").exists()
    assert Path(tmp_base_dir, "detectors", "det_123", "audits").exists()
    assert Path(tmp_base_dir, "detectors", "det_456", "iqs").exists()
    assert Path(tmp_base_dir, "detectors", "det_456", "escalations").exists()

    # All hourly files within the last 3 hours should be kept
    assert Path(tmp_base_dir, "iqs_2025-04-03_10").exists()
    assert Path(tmp_base_dir, "iqs_2025-04-03_11").exists()
    assert Path(tmp_base_dir, "iqs_2025-04-03_12").exists()
    assert Path(tmp_base_dir, "detectors", "det_123", "iqs_2025-04-03_10").exists()
    assert Path(tmp_base_dir, "detectors", "det_123", "iqs_2025-04-03_11").exists()
    assert Path(tmp_base_dir, "detectors", "det_123", "iqs_2025-04-03_12").exists()
    assert Path(tmp_base_dir, "detectors", "det_123", "escalations_2025-04-03_12").exists()
    assert Path(tmp_base_dir, "detectors", "det_123", "audits_2025-04-03_12").exists()

    # All hourly files outside of the last 3 hours should be deleted
    assert not Path(tmp_base_dir, "iqs_2025-04-03_08").exists(), f"all files in {tmp_base_dir} are {list(Path(tmp_base_dir).iterdir())}"
    assert not Path(tmp_base_dir, "iqs_2025-04-03_09").exists()
    assert not Path(tmp_base_dir, "detectors", "det_123", "iqs_2025-04-03_08").exists()
    assert not Path(tmp_base_dir, "detectors", "det_123", "iqs_2025-04-03_09").exists()
    assert not Path(tmp_base_dir, "detectors", "det_456", "iqs_2010-04-03_09").exists()
