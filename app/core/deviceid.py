"""Simple device ID management.
We need a way to identify the device, and we need to be able to generate a new one if needed.
The device ID is stored in a JSON file, normally at /opt/groundlight/device/id.json
When we generate it, it has a few fields:
- uuid: The unique device ID
- friendly_name: A friendly name for the device
- created_at: The date and time the device ID was created

UUID is the only required field.  Customers are encouraged to update the friendly name, and
even add extra fields if they want.

For this to work robustly in a containerized environment, we need /opt/groundlight/device/
mounted on the host using hostPath.
"""

import json
import logging
import os
from datetime import datetime

from app.core.utils import prefixed_ksuid

WELL_KNOWN_PATH = "/opt/groundlight/device/"
DEVICE_ID_FILE = f"{WELL_KNOWN_PATH}/id.json"

logger = logging.getLogger(__name__)


def _generate_deviceid_dict() -> dict:
    """Generate a new device ID dictionary with default fields."""
    unique_id = prefixed_ksuid("device")
    friendly_name = f"Device-{unique_id[-5:]}"
    return {"uuid": unique_id, "friendly_name": friendly_name, "created_at": datetime.now().isoformat()}


def _save_new_deviceid_dict() -> dict:
    """Generate and save a new device ID data to the JSON file."""
    deviceid_dict = _generate_deviceid_dict()
    logger.info(f"Generating and saving new device ID: {deviceid_dict['uuid']}")
    os.makedirs(WELL_KNOWN_PATH, exist_ok=True)
    with open(DEVICE_ID_FILE, "w") as f:
        json.dump(deviceid_dict, f, indent=2)
    return deviceid_dict


def _load_deviceid_dict() -> dict | None:
    """Tries to load the device ID record from the JSON file.
    Returns a dictionary with the device data, or None if invalid/not found.
    The only required field is 'uuid'.
    """
    if not os.path.exists(DEVICE_ID_FILE):
        return None
    try:
        with open(DEVICE_ID_FILE, "r") as f:
            data = json.load(f)

        if "uuid" in data:
            return data
        logger.warning(f"Device ID file {DEVICE_ID_FILE} exists but is missing uuid. Generating new one.")
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(f"Failed to parse device ID file: {e}. Generating new one.", exc_info=True)

    return None


def get_deviceid_dict() -> dict:
    """Get the device ID data dictionary, generating a new one if needed.

    Returns:
        dict: A dictionary containing at least 'uuid', and probably 'friendly_name' and 'created_at'.
              May contain additional fields added by users.
    """
    data = _load_deviceid_dict()
    if data is None:
        data = _save_new_deviceid_dict()
    return data


def get_deviceid_str() -> str:
    """Get the unique device ID string."""
    return get_deviceid_dict()["uuid"]
