import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from groundlight.edge import EdgeEndpointConfig, DetectorConfig

from app.core.database import DatabaseManager
from app.core.edge_config_loader import apply_detector_changes, compute_detector_diff


def _config_with_detectors(*detector_ids: str) -> EdgeEndpointConfig:
    """Helper to build an EdgeEndpointConfig with the given detector IDs."""
    config = EdgeEndpointConfig()
    for did in detector_ids:
        config.detectors.append(DetectorConfig(detector_id=did, edge_inference_config="default"))
    return config


def test_compute_detector_diff_no_changes():
    removed, added = compute_detector_diff({"det_A", "det_B"}, _config_with_detectors("det_A", "det_B"))
    assert removed == set()
    assert added == set()


def test_compute_detector_diff_all_added():
    removed, added = compute_detector_diff(set(), _config_with_detectors("det_A", "det_B"))
    assert removed == set()
    assert added == {"det_A", "det_B"}


def test_compute_detector_diff_all_removed():
    removed, added = compute_detector_diff({"det_A", "det_B"}, _config_with_detectors())
    assert removed == {"det_A", "det_B"}
    assert added == set()


def test_compute_detector_diff_mixed():
    removed, added = compute_detector_diff(
        {"det_A", "det_B", "det_C"},
        _config_with_detectors("det_B", "det_D"),
    )
    assert removed == {"det_A", "det_C"}
    assert added == {"det_D"}


def test_compute_detector_diff_empty_both():
    removed, added = compute_detector_diff(set(), _config_with_detectors())
    assert removed == set()
    assert added == set()


def test_compute_detector_diff_filters_empty_detector_ids():
    """Detectors with empty-string IDs in the config should be ignored."""
    removed, added = compute_detector_diff(set(), _config_with_detectors("det_A", ""))
    assert added == {"det_A"}


@pytest.fixture(scope="module")
def db_manager():
    db_manager = DatabaseManager(verbose=False)
    engine = create_engine("sqlite:///:memory:", echo=False)
    db_manager._engine = engine
    db_manager.session_maker = sessionmaker(bind=engine)
    db_manager.create_tables()
    yield db_manager
    db_manager.shutdown()


@pytest.fixture(autouse=True)
def reset_db(db_manager):
    db_manager.reset_database()


def test_apply_detector_changes_adds_records(db_manager):
    apply_detector_changes(removed=set(), added={"det_X", "det_Y"}, db_manager=db_manager)

    records = db_manager.get_inference_deployment_records()
    detector_ids = {r.detector_id for r in records}
    assert detector_ids == {"det_X", "det_Y"}
    for r in records:
        assert not r.deployment_created
        assert not r.pending_deletion


def test_apply_detector_changes_marks_removal(db_manager):
    apply_detector_changes(removed=set(), added={"det_A"}, db_manager=db_manager)
    apply_detector_changes(removed={"det_A"}, added=set(), db_manager=db_manager)

    records = db_manager.get_inference_deployment_records(detector_id="det_A")
    assert len(records) > 0
    for r in records:
        assert r.pending_deletion


def test_apply_detector_changes_noop_when_empty(db_manager):
    apply_detector_changes(removed=set(), added=set(), db_manager=db_manager)
    records = db_manager.get_inference_deployment_records()
    assert len(records) == 0
