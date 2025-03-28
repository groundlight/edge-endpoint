"""Tests for the deviceid module."""

import json
from unittest.mock import patch

from app.core import deviceid


def test_load_device_id_file_exists(monkeypatch, tmp_path):
    """Test loading a device ID when the file exists and has a valid ID."""
    # Setup a temporary directory for the test
    test_device_path = tmp_path / "device"
    test_device_path.mkdir()
    test_device_id_file = test_device_path / "id.json"
    test_device_id = "device_testid123456789"
    test_friendly_name = "Device-56789"
    test_created_at = "2023-01-01T12:00:00"

    # Create a valid device record JSON
    device_record = {"uuid": test_device_id, "friendly_name": test_friendly_name, "created_at": test_created_at}

    with open(test_device_id_file, "w") as f:
        json.dump(device_record, f)

    # Patch the paths
    monkeypatch.setattr(deviceid, "WELL_KNOWN_PATH", str(tmp_path / "device"))
    monkeypatch.setattr(deviceid, "DEVICE_ID_FILE", str(test_device_id_file))

    # Check that the function loads the correct ID
    loaded_record = deviceid._load_deviceid_dict()
    assert loaded_record is not None
    assert loaded_record["uuid"] == test_device_id
    assert loaded_record["friendly_name"] == test_friendly_name
    assert loaded_record["created_at"] == test_created_at


def test_load_device_id_file_not_exists(monkeypatch, tmp_path):
    """Test loading a device ID when the file doesn't exist."""
    # Setup a temporary directory for the test
    test_device_path = tmp_path / "device"
    test_device_id_file = test_device_path / "id.json"

    # Patch the paths
    monkeypatch.setattr(deviceid, "WELL_KNOWN_PATH", str(test_device_path))
    monkeypatch.setattr(deviceid, "DEVICE_ID_FILE", str(test_device_id_file))

    # Check that the function returns None
    assert deviceid._load_deviceid_dict() is None


def test_load_device_id_invalid_content(monkeypatch, tmp_path):
    """Test loading a device ID when the file contains invalid data."""
    # Setup a temporary directory for the test
    test_device_path = tmp_path / "device"
    test_device_path.mkdir()
    test_device_id_file = test_device_path / "id.json"

    # Write invalid JSON
    test_device_id_file.write_text("invalid_json_format")

    # Patch the paths
    monkeypatch.setattr(deviceid, "WELL_KNOWN_PATH", str(test_device_path))
    monkeypatch.setattr(deviceid, "DEVICE_ID_FILE", str(test_device_id_file))

    # Check that the function returns None for invalid content
    assert deviceid._load_deviceid_dict() is None


def test_load_device_id_missing_uuid(monkeypatch, tmp_path):
    """Test loading a device ID when the JSON is missing the uuid field."""
    # Setup a temporary directory for the test
    test_device_path = tmp_path / "device"
    test_device_path.mkdir()
    test_device_id_file = test_device_path / "id.json"

    # Create invalid device record JSON (missing uuid)
    device_record = {"friendly_name": "Test-Device", "created_at": "2023-01-01T12:00:00"}

    with open(test_device_id_file, "w") as f:
        json.dump(device_record, f)

    # Patch the paths
    monkeypatch.setattr(deviceid, "WELL_KNOWN_PATH", str(test_device_path))
    monkeypatch.setattr(deviceid, "DEVICE_ID_FILE", str(test_device_id_file))

    # Check that the function returns None for invalid content
    assert deviceid._load_deviceid_dict() is None


def test_save_new_device_id(monkeypatch, tmp_path):
    """Test saving a new device ID."""
    # Setup a temporary directory for the test
    test_device_path = tmp_path / "device"
    test_device_id_file = test_device_path / "id.json"

    # Patch the paths
    monkeypatch.setattr(deviceid, "WELL_KNOWN_PATH", str(test_device_path))
    monkeypatch.setattr(deviceid, "DEVICE_ID_FILE", str(test_device_id_file))

    # First check that the file is not there.
    assert deviceid._load_deviceid_dict() is None

    # Setup test data
    test_device_id = "device_testid123456789"
    test_friendly_name = "Device-56789"
    test_created_at = "2023-01-01T12:00:00"

    mock_record = {"uuid": test_device_id, "friendly_name": test_friendly_name, "created_at": test_created_at}

    # Mock the generate function to return a predictable record
    with patch("app.core.deviceid._generate_deviceid_dict", return_value=mock_record):
        device_record = deviceid.get_deviceid_metadata_dict()
        device_id = deviceid.get_deviceid_str()

    # Check that we got the expected record
    assert device_record["uuid"] == test_device_id
    assert device_record["friendly_name"] == test_friendly_name
    assert device_record["created_at"] == test_created_at

    # Check that get_deviceid_str returns just the uuid string
    assert device_id == test_device_id

    # Check that the file was created with the correct content
    with open(test_device_id_file, "r") as f:
        saved_data = json.load(f)

    assert saved_data["uuid"] == test_device_id
    assert saved_data["friendly_name"] == test_friendly_name
    assert saved_data["created_at"] == test_created_at
    assert test_device_path.exists()


def test_get_device_id_existing(monkeypatch, tmp_path):
    """Test getting a device ID when it already exists."""
    # Setup a temporary directory for the test
    test_device_path = tmp_path / "device"
    test_device_path.mkdir()
    test_device_id_file = test_device_path / "id.json"

    # Create a valid device record JSON
    test_device_id = "device_testid123456789"
    test_friendly_name = "Device-56789"
    test_created_at = "2023-01-01T12:00:00"

    device_record = {"uuid": test_device_id, "friendly_name": test_friendly_name, "created_at": test_created_at}

    with open(test_device_id_file, "w") as f:
        json.dump(device_record, f)

    # Patch the paths
    monkeypatch.setattr(deviceid, "WELL_KNOWN_PATH", str(test_device_path))
    monkeypatch.setattr(deviceid, "DEVICE_ID_FILE", str(test_device_id_file))

    # Check that get_deviceid_str returns just the uuid string
    assert deviceid.get_deviceid_str() == test_device_id

    # Check that get_deviceid_dict returns the full record
    record = deviceid.get_deviceid_metadata_dict()
    assert record["uuid"] == test_device_id
    assert record["friendly_name"] == test_friendly_name
    assert record["created_at"] == test_created_at


def test_get_device_id_new(monkeypatch, tmp_path):
    """Test getting a device ID when it needs to be created."""
    # Setup a temporary directory for the test
    test_device_path = tmp_path / "device"
    test_device_id_file = test_device_path / "id.json"

    # Patch the paths
    monkeypatch.setattr(deviceid, "WELL_KNOWN_PATH", str(test_device_path))
    monkeypatch.setattr(deviceid, "DEVICE_ID_FILE", str(test_device_id_file))

    # Setup test data
    test_device_id = "device_testid123456789"
    test_friendly_name = "Device-56789"
    test_created_at = "2023-01-01T12:00:00"

    mock_record = {"uuid": test_device_id, "friendly_name": test_friendly_name, "created_at": test_created_at}

    # Mock the generate function to return a predictable record
    with patch("app.core.deviceid._generate_deviceid_dict", return_value=mock_record):
        device_id = deviceid.get_deviceid_str()

    # Check that the function returns the new ID
    assert device_id == test_device_id

    # Check that the file was created with the correct content
    with open(test_device_id_file, "r") as f:
        saved_data = json.load(f)

    assert saved_data["uuid"] == test_device_id
    assert saved_data["friendly_name"] == test_friendly_name
    assert saved_data["created_at"] == test_created_at
