"""Tests for the deviceid module."""
from unittest.mock import patch

from app.core import deviceid


def test_load_device_id_file_exists(monkeypatch, tmp_path):
    """Test loading a device ID when the file exists and has a valid ID."""
    # Setup a temporary directory for the test
    test_device_path = tmp_path / "device"
    test_device_path.mkdir()
    test_device_id_file = test_device_path / "deviceid.txt"
    test_device_id = "device_testid123456789"
    test_device_id_file.write_text(test_device_id)
    
    # Patch the paths
    monkeypatch.setattr(deviceid, "WELL_KNOWN_PATH", str(tmp_path / "device"))
    monkeypatch.setattr(deviceid, "DEVICE_ID_FILE", str(test_device_id_file))
    
    # Check that the function loads the correct ID
    assert deviceid._load_device_id() == test_device_id


def test_load_device_id_file_not_exists(monkeypatch, tmp_path):
    """Test loading a device ID when the file doesn't exist."""
    # Setup a temporary directory for the test
    test_device_path = tmp_path / "device"
    test_device_id_file = test_device_path / "deviceid.txt"
    
    # Patch the paths
    monkeypatch.setattr(deviceid, "WELL_KNOWN_PATH", str(test_device_path))
    monkeypatch.setattr(deviceid, "DEVICE_ID_FILE", str(test_device_id_file))
    
    # Check that the function returns None
    assert deviceid._load_device_id() is None


def test_load_device_id_invalid_content(monkeypatch, tmp_path):
    """Test loading a device ID when the file contains invalid data."""
    # Setup a temporary directory for the test
    test_device_path = tmp_path / "device"
    test_device_path.mkdir()
    test_device_id_file = test_device_path / "deviceid.txt"
    test_device_id_file.write_text("invalid_id_format")
    
    # Patch the paths
    monkeypatch.setattr(deviceid, "WELL_KNOWN_PATH", str(test_device_path))
    monkeypatch.setattr(deviceid, "DEVICE_ID_FILE", str(test_device_id_file))
    
    # Check that the function returns None for invalid content
    assert deviceid._load_device_id() is None


def test_save_new_device_id(monkeypatch, tmp_path):
    """Test saving a new device ID."""
    # Setup a temporary directory for the test
    test_device_path = tmp_path / "device"
    test_device_id_file = test_device_path / "deviceid.txt"
    
    # Patch the paths
    monkeypatch.setattr(deviceid, "WELL_KNOWN_PATH", str(test_device_path))
    monkeypatch.setattr(deviceid, "DEVICE_ID_FILE", str(test_device_id_file))
    
    # First check that the file is not there.
    assert deviceid._load_device_id() is None

    # Mock the prefixed_ksuid function to return a predictable ID
    test_device_id = "device_testid123456789"
    with patch("app.core.deviceid.prefixed_ksuid", return_value=test_device_id):
        device_id = deviceid.get_device_id()

    assert device_id == test_device_id
    assert test_device_id_file.read_text() == test_device_id
    assert test_device_path.exists()


def test_get_device_id_existing(monkeypatch, tmp_path):
    """Test getting a device ID when it already exists."""
    # Setup a temporary directory for the test
    test_device_path = tmp_path / "device"
    test_device_path.mkdir()
    test_device_id_file = test_device_path / "deviceid.txt"
    test_device_id = "device_testid123456789"
    test_device_id_file.write_text(test_device_id)
    
    # Patch the paths
    monkeypatch.setattr(deviceid, "WELL_KNOWN_PATH", str(test_device_path))
    monkeypatch.setattr(deviceid, "DEVICE_ID_FILE", str(test_device_id_file))
    
    # Check that the function returns the existing ID
    assert deviceid.get_device_id() == test_device_id


def test_get_device_id_new(monkeypatch, tmp_path):
    """Test getting a device ID when it needs to be created."""
    # Setup a temporary directory for the test
    test_device_path = tmp_path / "device"
    test_device_id_file = test_device_path / "deviceid.txt"
    
    # Patch the paths
    monkeypatch.setattr(deviceid, "WELL_KNOWN_PATH", str(test_device_path))
    monkeypatch.setattr(deviceid, "DEVICE_ID_FILE", str(test_device_id_file))
    
    # Mock the prefixed_ksuid function to return a predictable ID
    test_device_id = "device_testid123456789"
    with patch("app.core.deviceid.prefixed_ksuid", return_value=test_device_id):
        device_id = deviceid.get_device_id()
    
    # Check that the function returns the new ID and writes it to the file
    assert device_id == test_device_id
    assert test_device_id_file.read_text() == test_device_id
