import os
import stat
from unittest.mock import MagicMock, patch

import pytest
import yaml
from groundlight.edge import DEFAULT, EdgeEndpointConfig, InferenceConfig
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import DatabaseManager
from app.core.edge_config_manager import EdgeConfigManager, apply_detector_changes, compute_detector_diff

DET_A = "det_AAAAAAAAAAAAAAAAAAAAAAAAAAA"
DET_B = "det_BBBBBBBBBBBBBBBBBBBBBBBBBBB"
DET_C = "det_CCCCCCCCCCCCCCCCCCCCCCCCCCC"
DET_D = "det_DDDDDDDDDDDDDDDDDDDDDDDDDDD"


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
    """Tests for EdgeConfigManager save/active and mtime caching."""

    @pytest.fixture(autouse=True)
    def isolated_config(self, tmp_path, monkeypatch):
        """Point config paths at temp files and reset class-level cache between tests."""
        self.active_path = str(tmp_path / "active-edge-config.yaml")
        monkeypatch.setattr("app.core.edge_config_manager.ACTIVE_EDGE_CONFIG_PATH", self.active_path)
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
        assert first is second

    def test_active_reloads_on_file_change(self):
        EdgeConfigManager.save(_config_with_detectors(DET_A))
        first = EdgeConfigManager.active()

        EdgeConfigManager.save(_config_with_detectors(DET_B))
        second = EdgeConfigManager.active()
        assert first is not second
        assert {d.detector_id for d in second.detectors} == {DET_B}

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


class TestSaveIsAtomic:
    @pytest.fixture(autouse=True)
    def isolated_config(self, tmp_path, monkeypatch):
        self.config_dir = tmp_path
        self.active_path = str(tmp_path / "active-edge-config.yaml")
        monkeypatch.setattr("app.core.edge_config_manager.ACTIVE_EDGE_CONFIG_PATH", self.active_path)

    def _read(self) -> str:
        with open(self.active_path) as f:
            return f.read()

    def test_readers_see_the_old_config_until_the_new_one_is_complete(self, monkeypatch):
        EdgeConfigManager.save(_config_with_detectors(DET_A))
        old = self._read()
        seen_mid_write = []
        real_dump = yaml.dump

        def dump_and_peek(*args, **kwargs):
            seen_mid_write.append(self._read())
            return real_dump(*args, **kwargs)

        monkeypatch.setattr("app.core.edge_config_manager.yaml.dump", dump_and_peek)
        EdgeConfigManager.save(_config_with_detectors(DET_B))

        assert seen_mid_write == [old]
        assert {d.detector_id for d in EdgeConfigManager.load_strict().detectors} == {DET_B}

    def test_replaces_the_file_from_a_temp_file_in_the_same_directory(self):
        with patch("app.core.edge_config_manager.os.replace", wraps=os.replace) as replace:
            EdgeConfigManager.save(_config_with_detectors(DET_A))

        [(src, dst)] = [c.args for c in replace.call_args_list]
        assert os.path.dirname(src) == str(self.config_dir)
        assert dst == self.active_path
        assert os.listdir(self.config_dir) == ["active-edge-config.yaml"]
        world_readable = stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH
        assert stat.S_IMODE(os.stat(self.active_path).st_mode) == world_readable

    def test_a_failed_write_leaves_the_old_config_and_no_temp_file(self, monkeypatch):
        EdgeConfigManager.save(_config_with_detectors(DET_A))
        old = self._read()
        monkeypatch.setattr("app.core.edge_config_manager.yaml.dump", MagicMock(side_effect=OSError("disk full")))

        with pytest.raises(OSError, match="disk full"):
            EdgeConfigManager.save(_config_with_detectors(DET_B))

        assert self._read() == old
        assert os.listdir(self.config_dir) == ["active-edge-config.yaml"]


class TestLoadStrict:
    @pytest.fixture(autouse=True)
    def isolated_config(self, tmp_path, monkeypatch):
        self.active_path = tmp_path / "active-edge-config.yaml"
        monkeypatch.setattr("app.core.edge_config_manager.ACTIVE_EDGE_CONFIG_PATH", str(self.active_path))

    def test_reads_a_saved_config(self):
        EdgeConfigManager.save(_config_with_detectors(DET_A, DET_B))
        assert {d.detector_id for d in EdgeConfigManager.load_strict().detectors} == {DET_A, DET_B}

    def test_a_saved_config_with_no_detectors_is_valid(self):
        EdgeConfigManager.save(EdgeEndpointConfig())
        assert EdgeConfigManager.load_strict().detectors == []

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            EdgeConfigManager.load_strict()

    @pytest.mark.parametrize("content", ["", "   \n\t\n", "{}", "null", "# just a comment\n", "- a\n- b\n"])
    def test_empty_or_non_mapping_file_raises(self, content):
        """active() would read any of these as the default config, which has no detectors."""
        self.active_path.write_text(content)
        with pytest.raises(ValueError):
            EdgeConfigManager.load_strict()

    @pytest.mark.parametrize(
        "content",
        ["detectors: [unclosed\n", "detectors:\n  - detector_id: det_x\n    edge_inference_config: no_such_config\n"],
    )
    def test_invalid_file_raises(self, content):
        self.active_path.write_text(content)
        with pytest.raises(ValueError):
            EdgeConfigManager.load_strict()

    def test_does_not_touch_the_active_cache(self):
        EdgeConfigManager._cached_config = sentinel = EdgeEndpointConfig()
        EdgeConfigManager._cached_mtime = 0.0
        EdgeConfigManager.save(_config_with_detectors(DET_A))

        EdgeConfigManager.load_strict()

        assert EdgeConfigManager._cached_config is sentinel
