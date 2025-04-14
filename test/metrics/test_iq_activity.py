import os
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from app.metrics.iq_activity import (
    ActivityRetriever,
    FilesystemActivityTrackingHelper,
    clear_old_activity_files,
    record_activity_for_metrics,
)


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


def test_activity_tracking(monkeypatch, tmp_base_dir, _test_tracker):
    monkeypatch.setattr("app.metrics.iq_activity._tracker", lambda: _test_tracker)
    monkeypatch.setattr(os, "getpid", lambda: 12345)

    # Record an IQ, check that the last_iq file, iqs file, and detector-specific iqs file are all
    # created and have the correct values
    with patch("app.metrics.iq_activity.datetime") as mock_datetime:
        mock_datetime.now.return_value = datetime(2025, 4, 3, 12, 0, 0)

        # Record an IQ, make sure that an hourly file is created with the right PID for this detector
        record_activity_for_metrics("det_recordactivitytest", "iqs")
        assert Path(tmp_base_dir, "detectors", "det_recordactivitytest", "iqs_12345_2025-04-03_12").exists()
        assert Path(tmp_base_dir, "detectors", "det_recordactivitytest", "iqs_12345_2025-04-03_12").read_text() == "1"
        # Also make sure that the last_iqs file is created and updated correctly for the edge endpoint and the individual detector
        assert Path(tmp_base_dir, "detectors", "det_recordactivitytest", "last_iqs").exists()
        # assert Path(tmp_base_dir, "last_iqs").exists()

        # Record another IQ, it updates the hourly file for the same PID
        record_activity_for_metrics("det_recordactivitytest", "iqs")
        assert Path(tmp_base_dir, "detectors", "det_recordactivitytest", "iqs_12345_2025-04-03_12").read_text() == "2"

        # Switch PIDs, and then make sure a new hourly file is created and the one for the other PID remains the same
        monkeypatch.setattr(os, "getpid", lambda: 67890)

        record_activity_for_metrics("det_recordactivitytest", "iqs")
        assert Path(tmp_base_dir, "detectors", "det_recordactivitytest", "iqs_67890_2025-04-03_12").exists()
        assert Path(tmp_base_dir, "detectors", "det_recordactivitytest", "iqs_67890_2025-04-03_12").read_text() == "1"
        assert Path(tmp_base_dir, "detectors", "det_recordactivitytest", "iqs_12345_2025-04-03_12").read_text() == "2"

        # Record an escalation and an audit, make sure the detector-specific files are created and have
        # the correct values
        record_activity_for_metrics("det_recordactivitytest", "escalations")
        assert Path(tmp_base_dir, "detectors", "det_recordactivitytest", "escalations_67890_2025-04-03_12").exists()
        assert (
            Path(tmp_base_dir, "detectors", "det_recordactivitytest", "escalations_67890_2025-04-03_12").read_text()
            == "1"
        )
        record_activity_for_metrics("det_recordactivitytest", "audits")
        assert Path(tmp_base_dir, "detectors", "det_recordactivitytest", "audits_67890_2025-04-03_12").exists()
        assert (
            Path(tmp_base_dir, "detectors", "det_recordactivitytest", "audits_67890_2025-04-03_12").read_text() == "1"
        )


def test_wrong_activity_type():
    with pytest.raises(ValueError):
        record_activity_for_metrics("det_123", "wrong_activity_type")


def test_clear_old_activity_files(monkeypatch, tmp_base_dir, _test_tracker):
    monkeypatch.setattr("app.metrics.iq_activity._tracker", lambda: _test_tracker)
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

    with patch("app.metrics.iq_activity.datetime") as mock_datetime:
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
    assert not Path(
        tmp_base_dir, "iqs_2025-04-03_08"
    ).exists(), f"all files in {tmp_base_dir} are {list(Path(tmp_base_dir).iterdir())}"
    assert not Path(tmp_base_dir, "iqs_2025-04-03_09").exists()
    assert not Path(tmp_base_dir, "detectors", "det_123", "iqs_2025-04-03_08").exists()
    assert not Path(tmp_base_dir, "detectors", "det_123", "iqs_2025-04-03_09").exists()
    assert not Path(tmp_base_dir, "detectors", "det_456", "iqs_2010-04-03_09").exists()


def test_get_detector_activity_metrics(monkeypatch, tmp_base_dir, _test_tracker):
    monkeypatch.setattr("app.metrics.iq_activity._tracker", lambda: _test_tracker)
    with patch("app.metrics.iq_activity.datetime") as mock_datetime:
        mock_datetime.now.return_value = datetime(2025, 4, 3, 12, 0, 0)
        retriever = ActivityRetriever()

        # Total iqs should be 28, total escalations should be 2, and total audits should be 1
        os.makedirs(Path(tmp_base_dir, "detectors", "det_123"), exist_ok=True)
        Path(tmp_base_dir, "detectors", "det_123", "iqs_10294_2025-04-03_11").write_text("10")
        Path(tmp_base_dir, "detectors", "det_123", "iqs_12323_2025-04-03_11").write_text("1")
        Path(tmp_base_dir, "detectors", "det_123", "iqs_12345_2025-04-03_11").write_text("17")
        Path(tmp_base_dir, "detectors", "det_123", "escalations_102394_2025-04-03_11").write_text("2")
        Path(tmp_base_dir, "detectors", "det_123", "audits_102394_2025-04-03_11").write_text("1")
        Path(tmp_base_dir, "detectors", "det_123", "last_iqs").touch()
        Path(tmp_base_dir, "detectors", "det_123", "last_escalations").touch()
        Path(tmp_base_dir, "detectors", "det_123", "last_audits").touch()
        det_123_metrics = retriever.get_detector_activity_metrics("det_123")
        assert det_123_metrics["total_iqs"] == 28
        assert det_123_metrics["total_escalations"] == 2
        assert det_123_metrics["total_audits"] == 1
        assert det_123_metrics["last_iqs"] != "none"
        assert det_123_metrics["last_escalations"] != "none"
        assert det_123_metrics["last_audits"] != "none"

        # Test that it's fine to have an activity type missing
        # Total iqs should be 10, total escalations should be 1, and total audits should be 0
        os.makedirs(Path(tmp_base_dir, "detectors", "det_456"), exist_ok=True)
        Path(tmp_base_dir, "detectors", "det_456", "iqs_102394_2025-04-03_11").write_text("10")
        Path(tmp_base_dir, "detectors", "det_456", "escalations_12345_2025-04-03_11").write_text("1")
        Path(tmp_base_dir, "detectors", "det_456", "last_iqs").touch()
        Path(tmp_base_dir, "detectors", "det_456", "last_escalations").touch()
        det_456_metrics = retriever.get_detector_activity_metrics("det_456")
        assert det_456_metrics["total_iqs"] == 10
        assert det_456_metrics["total_escalations"] == 1
        assert det_456_metrics["total_audits"] == 0
        assert det_456_metrics["last_iqs"] != "none"
        assert det_456_metrics["last_escalations"] != "none"
        assert det_456_metrics["last_audits"] == "none"

        # Test that it's fine to have empty files or files that contain "0"
        # Total iqs should be 80, total escalations and audits should both be 0
        os.makedirs(Path(tmp_base_dir, "detectors", "det_789"), exist_ok=True)
        Path(tmp_base_dir, "detectors", "det_789", "iqs_10294_2025-04-03_11").write_text("80")
        Path(tmp_base_dir, "detectors", "det_789", "iqs_12345_2025-04-03_11").write_text("0")
        Path(tmp_base_dir, "detectors", "det_789", "iqs_12345_2025-04-03_11").write_text("")
        Path(tmp_base_dir, "detectors", "det_789", "escalations_102394_2025-04-03_11").write_text("0")
        Path(tmp_base_dir, "detectors", "det_789", "audits_102394_2025-04-03_11").write_text("")
        det_789_metrics = retriever.get_detector_activity_metrics("det_789")
        assert det_789_metrics["total_iqs"] == 80
        assert det_789_metrics["total_escalations"] == 0
        assert det_789_metrics["total_audits"] == 0
        assert det_789_metrics["last_iqs"] == "none"
        assert det_789_metrics["last_escalations"] == "none"
        assert det_789_metrics["last_audits"] == "none"
