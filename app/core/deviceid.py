"""Extremely simple device ID management.
We need a way to identify the device, and we need to be able to generate a new one if needed.

For this to work properly in a containerized environment, we want the WELL_KNOWN_PATH to be 
mounted on the host using hostPath.
"""
import logging
import os

from app.core.utils import prefixed_ksuid

WELL_KNOWN_PATH = "/opt/groundlight/device/"
DEVICE_ID_FILE = f"{WELL_KNOWN_PATH}/deviceid.txt"

logger = logging.getLogger(__name__)

def _save_new_device_id() -> str:
    device_id = prefixed_ksuid("device")
    logger.info(f"Generating and saving new device ID: {device_id}")
    os.makedirs(WELL_KNOWN_PATH, exist_ok=True)
    with open(DEVICE_ID_FILE, "w") as f:
        f.write(device_id)
    return device_id

def _load_device_id() -> str | None:
    """Tries to load the device ID from the file.
    If the file does not exist, or doesn't look like a valid device ID, returns None.
    """
    if not os.path.exists(DEVICE_ID_FILE):
        return None
    with open(DEVICE_ID_FILE, "r") as f:
        out = f.read()
    if out.startswith("device_"):
        return out
    logger.warning(f"Device ID file {DEVICE_ID_FILE} exists but appears invalid. Generating new one.")
    return None

def get_device_id() -> str:
    out = _load_device_id()
    if out is None:
        out = _save_new_device_id()
    return out
