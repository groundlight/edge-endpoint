"""Extremely simple device ID management.
We need a way to identify the device, and we need to be able to generate a new one if needed.

For this to work properly in a containerized environment, we want the WELL_KNOWN_PATH to be
mounted on the host using hostPath.
"""

import json
import logging
import os
from datetime import datetime
from dataclasses import dataclass

from app.core.utils import prefixed_ksuid

WELL_KNOWN_PATH = "/opt/groundlight/device/"
DEVICE_ID_FILE = f"{WELL_KNOWN_PATH}/id.json"

logger = logging.getLogger(__name__)


@dataclass
class DeviceIdRecord:
    uuid: str
    friendly_name: str
    created_at: str


def _generate_deviceid_record() -> DeviceIdRecord:
    unique_id = prefixed_ksuid("device")
    friendly_name = f"Device-{unique_id[-5:]}"
    return DeviceIdRecord(uuid=unique_id, 
        friendly_name=friendly_name,
        created_at=datetime.now().isoformat()
    )


def _save_new_device_id() -> DeviceIdRecord:
    """Generate and save a new device ID record to the JSON file."""
    device_record = _generate_deviceid_record()
    logger.info(f"Generating and saving new device ID: {device_record.uuid}")
    os.makedirs(WELL_KNOWN_PATH, exist_ok=True)
    with open(DEVICE_ID_FILE, "w") as f:
        json.dump(device_record.__dict__, f, indent=2)
    return device_record


def _load_device_id() -> DeviceIdRecord | None:
    """Tries to load the device ID record from the JSON file.
    If the file does not exist, or doesn't look like a valid device ID record, returns None.
    """
    if not os.path.exists(DEVICE_ID_FILE):
        return None
    try:
        with open(DEVICE_ID_FILE, "r") as f:
            data = json.load(f)
        
        # Validate that we have the expected fields
        if "uuid" in data and data["uuid"].startswith("device_"):
            return DeviceIdRecord(**data)
        logger.warning(f"Device ID file {DEVICE_ID_FILE} exists but appears invalid. Generating new one.")
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(f"Failed to parse device ID file: {e}. Generating new one.")
    
    return None


def get_device_id_record() -> DeviceIdRecord:
    """Get the device ID record, generating a new one if needed."""
    record = _load_device_id()
    if record is None:
        record = _save_new_device_id()
    return record


def get_device_id() -> str:
    """Get the unique device ID string."""
    return get_device_id_record().uuid
