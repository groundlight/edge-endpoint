import csv
import sys

import pytest

import groundlight_helpers as glh
from measure_ram_and_vram_usage import (
    CSV_FIELDS,
    csv_resource_fields,
    from_runtime_dir,
    load_completed,
    load_detector_specs,
    parse_args,
    spec_key,
)


def test_load_detector_specs_expands_cartesian_product(tmp_path):
    yaml_path = tmp_path / "pipelines.yaml"
    yaml_path.write_text(
        """
BINARY:
  image_sizes:
    - [640, 480]
  pipelines:
    - binary-pipe
COUNT:
  n: [1, 2]
  image_sizes:
    - [640, 480]
    - [320, 240]
  pipelines:
    - count-pipe
"""
    )

    specs = load_detector_specs(yaml_path)

    assert len(specs) == 5
    assert specs[0] == {
        "detector_mode": "BINARY",
        "edge_pipeline_config": "binary-pipe",
        "n": None,
        "image_width": 640,
        "image_height": 480,
    }
    count_keys = {
        spec_key(spec)
        for spec in specs
        if spec["detector_mode"] == "COUNT"
    }
    assert count_keys == {
        ("COUNT", "count-pipe", 1, 640, 480),
        ("COUNT", "count-pipe", 1, 320, 240),
        ("COUNT", "count-pipe", 2, 640, 480),
        ("COUNT", "count-pipe", 2, 320, 240),
    }


def test_load_detector_specs_requires_image_sizes(tmp_path):
    yaml_path = tmp_path / "pipelines.yaml"
    yaml_path.write_text(
        """
BINARY:
  pipelines:
    - binary-pipe
"""
    )

    with pytest.raises(ValueError, match="image_sizes is required"):
        load_detector_specs(yaml_path)


def test_load_detector_specs_binary_rejects_n(tmp_path):
    yaml_path = tmp_path / "pipelines.yaml"
    yaml_path.write_text(
        """
BINARY:
  n: [2]
  image_sizes:
    - [640, 480]
  pipelines:
    - binary-pipe
"""
    )

    with pytest.raises(ValueError, match="BINARY does not accept"):
        load_detector_specs(yaml_path)


def test_load_completed_reads_recorded_specs(tmp_path):
    csv_path = tmp_path / "results.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerow({
            "mode": "COUNT",
            "n": "10",
            "pipeline": "count-pipe",
            "image_width": 640,
            "image_height": 480,
            "detector_id": "det_abc",
            "ready": True,
            "primary_vram_bytes": 1,
            "oodd_vram_bytes": 2,
            "total_vram_bytes": 3,
            "primary_ram_bytes": 4,
            "oodd_ram_bytes": 5,
            "total_ram_bytes": 6,
            "system_vram_used_bytes": 7,
            "system_vram_total_bytes": 8,
            "system_ram_used_bytes": 9,
            "system_ram_total_bytes": 10,
        })
        writer.writerow({
            "mode": "BINARY",
            "n": "",
            "pipeline": "binary-pipe",
            "image_width": 320,
            "image_height": 240,
            "detector_id": "det_def",
            "ready": False,
            "primary_vram_bytes": 1,
            "oodd_vram_bytes": 2,
            "total_vram_bytes": 3,
            "primary_ram_bytes": 4,
            "oodd_ram_bytes": 5,
            "total_ram_bytes": 6,
            "system_vram_used_bytes": 7,
            "system_vram_total_bytes": 8,
            "system_ram_used_bytes": 9,
            "system_ram_total_bytes": 10,
        })

    assert load_completed(csv_path) == {
        ("COUNT", "count-pipe", 10, 640, 480),
        ("BINARY", "binary-pipe", None, 320, 240),
    }


def test_from_runtime_dir_requires_run_artifacts(tmp_path):
    with pytest.raises(SystemExit, match="missing required file"):
        from_runtime_dir(tmp_path)


def test_parse_args_resume_rejects_conflicting_inputs(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "measure_ram_and_vram_usage.py",
            str(run_dir / "pipelines.yaml"),
            "--device-name",
            "jetson-01",
            "--resume",
            str(run_dir),
        ],
    )

    with pytest.raises(SystemExit):
        parse_args()


def test_num_priming_labels_scales_with_n():
    assert glh.num_priming_labels_for_n("BINARY", 2) == 30
    assert glh.num_priming_labels_for_n("MULTI_CLASS", 4) == 30
    assert glh.num_priming_labels_for_n("MULTI_CLASS", 20) == 100


def test_csv_resource_fields_reads_resources_json_schema():
    resources = {
        "system": {
            "ram_bytes": {"total": 16_000_000_000, "used": 8_000_000_000},
            "gpu": {"vram_bytes": {"total": 24_000_000_000, "used": 12_000_000_000}},
        },
        "detectors": [{
            "detector_id": "det_abc",
            "ram_bytes": {"primary": 1_000_000_000, "oodd": 200_000_000, "total": 1_200_000_000},
            "gpu": {"vram_bytes": {"primary": 3_000_000_000, "oodd": 500_000_000, "total": 3_500_000_000}},
        }],
    }
    det_entry = resources["detectors"][0]

    assert csv_resource_fields(det_entry, resources["system"]) == {
        "primary_vram_bytes": 3_000_000_000,
        "oodd_vram_bytes": 500_000_000,
        "total_vram_bytes": 3_500_000_000,
        "primary_ram_bytes": 1_000_000_000,
        "oodd_ram_bytes": 200_000_000,
        "total_ram_bytes": 1_200_000_000,
        "system_vram_used_bytes": 12_000_000_000,
        "system_vram_total_bytes": 24_000_000_000,
        "system_ram_used_bytes": 8_000_000_000,
        "system_ram_total_bytes": 16_000_000_000,
    }


def test_parse_args_rejects_invalid_batch_size(tmp_path, monkeypatch):
    yaml_path = tmp_path / "pipelines.yaml"
    yaml_path.write_text(
        """
BOUNDING_BOX:
  n: [1]
  image_sizes:
    - [640, 480]
  pipelines:
    - bbox-pipe
"""
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "measure_ram_and_vram_usage.py",
            str(yaml_path),
            "--device-name",
            "jetson-01",
            "--batch-size",
            "0",
        ],
    )

    with pytest.raises(SystemExit):
        parse_args()
