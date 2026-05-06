"""Schema-validation tests. Cover the validators added in app_benchmark/config.py."""

import textwrap
from pathlib import Path

import pytest

from app_benchmark.config import BenchmarkConfig, ConfigError, load_config


def _write_config(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "cfg.yaml"
    p.write_text(textwrap.dedent(body).strip() + "\n")
    return p


def _minimal_config_dict(**overrides) -> dict:
    base = {
        "schema_version": 1,
        "run": {
            "name": "smoke",
            "edge_endpoint_url": "http://localhost:30101",
        },
        "detectors": [
            {"name": "person_bbox", "type": "bounding_box"},
            {"name": "fall_binary", "type": "binary"},
        ],
        "lenses": [
            {
                "name": "fall_lens",
                "chain": [
                    {"detector": "person_bbox", "num_crops_into_next": 3},
                    {"detector": "fall_binary"},
                ],
                "target_fps": 5,
                "cameras": 2,
                "image": {
                    "base": "images/dog.jpeg",
                    "resolution": [640, 480],
                    "composite_objects": None,
                },
                "downstream_crop": {
                    "resize_to": [224, 224],
                    "padding_image": "images/cat.jpeg",
                },
            },
        ],
    }
    for k, v in overrides.items():
        base[k] = v
    return base


def test_valid_minimal_config_round_trips():
    cfg = BenchmarkConfig.model_validate(_minimal_config_dict())
    assert cfg.schema_version == 1
    assert cfg.lenses[0].chain[0].num_crops_into_next == 3


def test_unknown_detector_reference_rejected():
    raw = _minimal_config_dict()
    raw["lenses"][0]["chain"][0]["detector"] = "nope"
    with pytest.raises(Exception) as ei:
        BenchmarkConfig.model_validate(raw)
    assert "unknown detector" in str(ei.value)


def test_terminal_stage_with_num_crops_rejected():
    raw = _minimal_config_dict()
    raw["lenses"][0]["chain"][1]["num_crops_into_next"] = 5
    with pytest.raises(Exception) as ei:
        BenchmarkConfig.model_validate(raw)
    assert "num_crops_into_next" in str(ei.value)


def test_chained_lens_requires_downstream_crop():
    raw = _minimal_config_dict()
    raw["lenses"][0]["downstream_crop"] = None
    with pytest.raises(Exception) as ei:
        BenchmarkConfig.model_validate(raw)
    assert "downstream_crop" in str(ei.value)


def test_single_stage_lens_requires_explicit_composite_objects():
    raw = _minimal_config_dict()
    raw["lenses"][0]["chain"] = [{"detector": "person_bbox"}]
    raw["lenses"][0]["downstream_crop"] = None
    raw["lenses"][0]["image"]["composite_objects"] = None
    with pytest.raises(Exception) as ei:
        BenchmarkConfig.model_validate(raw)
    assert "composite_objects" in str(ei.value)


def test_single_stage_lens_with_composite_objects_ok():
    raw = _minimal_config_dict()
    raw["lenses"][0]["chain"] = [{"detector": "person_bbox"}]
    raw["lenses"][0]["downstream_crop"] = None
    raw["lenses"][0]["image"]["composite_objects"] = 3
    cfg = BenchmarkConfig.model_validate(raw)
    assert cfg.lenses[0].image.composite_objects == 3


def test_mlpipe_max_length():
    raw = _minimal_config_dict()
    raw["detectors"][0]["mlpipe"] = "a" * 101
    with pytest.raises(Exception) as ei:
        BenchmarkConfig.model_validate(raw)
    assert "mlpipe" in str(ei.value).lower() or "max_length" in str(ei.value).lower() or "string_too_long" in str(ei.value).lower()


def test_run_name_pattern():
    raw = _minimal_config_dict()
    raw["run"]["name"] = "has spaces"
    with pytest.raises(Exception):
        BenchmarkConfig.model_validate(raw)


def test_load_config_from_yaml_file(tmp_path):
    p = _write_config(tmp_path, """
        schema_version: 1
        run:
          name: smoke
          edge_endpoint_url: "http://localhost:30101"
        detectors:
          - name: bbox
            type: bounding_box
        lenses:
          - name: lens
            chain:
              - detector: bbox
            target_fps: 5
            cameras: 1
            image:
              base: images/dog.jpeg
              resolution: [640, 480]
              composite_objects: 3
    """)
    cfg = load_config(p)
    assert cfg.lenses[0].image.composite_objects == 3


def test_load_config_missing_file_raises_config_error(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "does-not-exist.yaml")
