import os

import pytest
from groundlight.edge import DEFAULT, EdgeEndpointConfig, InferenceConfig
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import DatabaseManager
from app.core.edge_config_manager import EdgeConfigManager, apply_detector_changes, compute_detector_diff

DET_A = "det_AAAAAAAAAAAAAAAAAAAAAAAAAAA"
DET_B = "det_BBBBBBBBBBBBBBBBBBBBBBBBBBB"
DET_C = "det_CCCCCCCCCCCCCCCCCCCCCCCCCCC"
DET_D = "det_DDDDDDDDDDDDDDDDDDDDDDDDDDD"
DET_ENV = "det_ENVENVENVENVENVENVENVENVENV"
DET_HELM = "det_HELMHELMHELMHELMHELMHELMHEL"
DET_PVC = "det_PVCPVCPVCPVCPVCPVCPVCPVCPVC"


def _config_with_detectors(*detector_ids: str) -> EdgeEndpointConfig:
    """Helper to build an EdgeEndpointConfig with the given detector IDs."""
    config = EdgeEndpointConfig()
    for did in detector_ids:
        config.add_detector(did, DEFAULT)
    return config


def test_compute_detector_diff_no_changes():
    removed, added = compute_detector_diff({DET_A, DET_B}, _config_with_detectors(DET_A, DET_B))
    assert removed == set()
    assert added == set()


def test_compute_detector_diff_all_added():
    removed, added = compute_detector_diff(set(), _config_with_detectors(DET_A, DET_B))
    assert removed == set()
    assert added == {DET_A, DET_B}


def test_compute_detector_diff_all_removed():
    removed, added = compute_detector_diff({DET_A, DET_B}, _config_with_detectors())
    assert removed == {DET_A, DET_B}
    assert added == set()


def test_compute_detector_diff_mixed():
    removed, added = compute_detector_diff(
        {DET_A, DET_B, DET_C},
        _config_with_detectors(DET_B, DET_D),
    )
    assert removed == {DET_A, DET_C}
    assert added == {DET_D}


def test_compute_detector_diff_empty_both():
    removed, added = compute_detector_diff(set(), _config_with_detectors())
    assert removed == set()
    assert added == set()


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


class TestEdgeConfigManager:
    """Tests for EdgeConfigManager save/active/load_startup_config and mtime caching."""

    @pytest.fixture(autouse=True)
    def isolated_config(self, tmp_path, monkeypatch):
        """Point config paths at temp files and reset class-level cache between tests."""
        self.active_path = str(tmp_path / "active-edge-config.yaml")
        self.helm_path = str(tmp_path / "helm-edge-config.yaml")
        monkeypatch.setattr("app.core.edge_config_manager.ACTIVE_EDGE_CONFIG_PATH", self.active_path)
        monkeypatch.setattr("app.core.edge_config_manager.HELM_EDGE_CONFIG_PATH", self.helm_path)
        monkeypatch.delenv("EDGE_CONFIG", raising=False)
        EdgeConfigManager._cached_config = EdgeEndpointConfig()
        EdgeConfigManager._cached_mtime = 0.0

    def test_save_and_active_roundtrip(self):
        config = _config_with_detectors(DET_A, DET_B)
        EdgeConfigManager.save(config)
        loaded = EdgeConfigManager.active()
        loaded_ids = {d.detector_id for d in loaded.detectors}
        assert loaded_ids == {DET_A, DET_B}

    def test_active_returns_defaults_when_no_file(self):
        result = EdgeConfigManager.active()
        assert result is not None
        assert isinstance(result, EdgeEndpointConfig)

    def test_active_uses_mtime_cache(self):
        config = _config_with_detectors(DET_A)
        EdgeConfigManager.save(config)

        first = EdgeConfigManager.active()
        second = EdgeConfigManager.active()
        assert first is second  # same object from cache, not re-read

    def test_active_reloads_on_file_change(self):
        EdgeConfigManager.save(_config_with_detectors(DET_A))
        first = EdgeConfigManager.active()

        EdgeConfigManager.save(_config_with_detectors(DET_B))
        second = EdgeConfigManager.active()
        assert first is not second
        assert {d.detector_id for d in second.detectors} == {DET_B}

    def test_load_startup_config_env_var(self, monkeypatch):
        monkeypatch.setenv(
            "EDGE_CONFIG",
            f'{{"edge_inference_configs": {{"default": {{"enabled": true}}}}, "detectors": [{{"detector_id": "{DET_ENV}", "edge_inference_config": "default"}}]}}',
        )
        config = EdgeConfigManager.load_startup_config()
        assert any(d.detector_id == DET_ENV for d in config.detectors)

    def test_load_startup_config_helm(self):
        helm_config = _config_with_detectors(DET_HELM)
        os.makedirs(os.path.dirname(self.helm_path), exist_ok=True)
        import yaml

        with open(self.helm_path, "w") as f:
            yaml.dump(helm_config.to_payload(), f)
        config = EdgeConfigManager.load_startup_config()
        assert any(d.detector_id == DET_HELM for d in config.detectors)

    def test_load_startup_config_active_pvc(self):
        pvc_config = _config_with_detectors(DET_PVC)
        EdgeConfigManager.save(pvc_config)
        config = EdgeConfigManager.load_startup_config()
        assert any(d.detector_id == DET_PVC for d in config.detectors)

    def test_load_startup_config_defaults(self):
        config = EdgeConfigManager.load_startup_config()
        assert isinstance(config, EdgeEndpointConfig)

    def test_load_startup_config_priority_env_over_helm(self, monkeypatch):
        """Env var should win even if Helm config exists."""
        monkeypatch.setenv(
            "EDGE_CONFIG",
            f'{{"edge_inference_configs": {{"default": {{"enabled": true}}}}, "detectors": [{{"detector_id": "{DET_ENV}", "edge_inference_config": "default"}}]}}',
        )
        import yaml

        with open(self.helm_path, "w") as f:
            yaml.dump(_config_with_detectors(DET_HELM).to_payload(), f)
        config = EdgeConfigManager.load_startup_config()
        ids = {d.detector_id for d in config.detectors}
        assert DET_ENV in ids
        assert DET_HELM not in ids

    def test_detector_configs(self):
        config = _config_with_detectors(DET_A, DET_B)
        result = EdgeConfigManager.detector_configs(config)
        assert set(result.keys()) == {DET_A, DET_B}
        assert all(isinstance(v, InferenceConfig) for v in result.values())

    def test_detector_config_found(self):
        config = _config_with_detectors(DET_A)
        result = EdgeConfigManager.detector_config(config, DET_A)
        assert isinstance(result, InferenceConfig)

    def test_detector_config_not_found(self):
        config = _config_with_detectors(DET_A)
        result = EdgeConfigManager.detector_config(config, "det_MISSING")
        assert result is None
