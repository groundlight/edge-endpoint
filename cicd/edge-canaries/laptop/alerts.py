import groundlight
from groundlight import VerbEnum, ApiException, Detector
import logging
import numpy as np

# TODO update this to the real pager duty inbox (edge-canary@groundlight.ai)
PAGER_DUTY_INBOX = 'tim@groundlight.ai'

logger = logging.getLogger(__name__)

# Connect to Groundlight Cloud
cloud_endpoint = 'https://api.groundlight.ai/device-api'
gl = groundlight.ExperimentalApi(endpoint=cloud_endpoint)

def create_heartbeat_alert(detector: Detector, heartbeat_timeout_minutes: int) -> None:
    """Sets up a heartbeat alert on Groundlight. Grounlight will send an email if the 
    relevant detector has not submitted an image query in with heartbeat_timeout_minutes.
    
    Use `send_heartbeat` to submit image queries.
    """
    verb = VerbEnum.NO_QUERIES
    parameters = {"time_value": heartbeat_timeout_minutes, "time_unit": "MINUTES"}
    condition = gl.make_condition(verb, parameters)
    
    action = gl.make_action(
        channel="EMAIL", 
        recipient=PAGER_DUTY_INBOX, 
        include_image=False, # heartbeat alert doesn't need an image
        )

    try:
        gl.create_alert(
            detector=detector,
            name="Canary Heartbeat",
            condition=condition,
            actions=action,
            enabled=True,
        )
        logger.info("New alert created successfully.")
    except ApiException as e:
        if "already exists" in e.body.lower():
            logger.info("Heartbeat alert already exists. Skipping...")
        else:
            logger.error(f'Unexpected error while creating a rule: {e}')
            
def send_heartbeat(detector: Detector, frame: np.ndarray) -> None:
    """Sends an image query to a detector to act as a heartbeat. 
    
    Use `create_heartbeat_alert` to create the relevant alert. 
    """
    gl.submit_image_query(detector, frame, human_review="NEVER", wait=0.0)
    logger.info('Heartbeat submitted!')