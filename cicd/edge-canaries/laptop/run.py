import groundlight
import framegrab
import time
import logging
import os
import sys

from alerts import create_hearbeat_alert, send_heartbeat

NUM_IMAGE_QUERIES = 1000

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S",
    force=True, # It seems one of framegrab's dependencies is causing an issue with this. See: https://github.com/groundlight/framegrab/pull/59
)

logger = logging.getLogger(__name__)

gl = groundlight.Groundlight()

detector_id = os.environ.get('DETECTOR_ID')
detector = gl.get_detector(detector_id)

# Create a new heartbeat detector based on the provided detector
heartbeat_detector = gl.get_or_create_detector(
    name = detector.name + " (Edge Canary Heartbeat)",
    query=detector.query
)

create_hearbeat_alert(heartbeat_detector, 15)

config = {
    "input_type": "rtsp",
    "id": {
        "rtsp_url": "{{RTSP_URL}}",
    },
    "options": {
        "max_fps": 30
    }
}
grabber = framegrab.FrameGrabber.create_grabber(config)

# Track all unique label values received
unique_labels = set()

logger.info(
    f'Starting laptop edge canary test. Submitting {NUM_IMAGE_QUERIES} image queries to {detector_id}...'
    )
test_start_time = time.time()
for n in range(NUM_IMAGE_QUERIES):
    
    frame = grabber.grab()
    
    iq = gl.submit_image_query(
        detector=detector,
        image=frame,
        human_review="NEVER",
        wait=0.0,
    )
    
    unique_labels.add(iq.result.label.value)
    
test_end_time = time.time()
test_duration = test_end_time - test_start_time
query_rate = NUM_IMAGE_QUERIES / test_duration
logger.info(f'Processed {NUM_IMAGE_QUERIES} image queries in {test_duration:.2f} seconds. {query_rate:.2f} queries per second.')

# Check that the query rate is sufficiently fast (edge speed)
# keep MINIMUM_EXPECTED_BINARY_QUERY_RATE on the conservative side to avoid alerting too much
# Queries might still escalate to cloud ML if unsure, which could slow things down.
MINIMUM_EXPECTED_BINARY_QUERY_RATE = 5.0 
if query_rate < MINIMUM_EXPECTED_BINARY_QUERY_RATE:
    logger.error(
        f"Edge Canary actual binary query rate is {query_rate}, less that expected minimum of {MINIMUM_EXPECTED_BINARY_QUERY_RATE}."
        f"There might be something wrong with the Edge Endpoint, or your detector ({detector_id}) might need more labels to function properly."
        )
    sys.exit(1) # exit to avoid sending heartbeat

# Check that the received labels are valid
EXPECTED_BINARY_LABELS = set(["YES", "NO", "UNSURE"])
unexpected_labels = unique_labels - EXPECTED_BINARY_LABELS
if len(unexpected_labels) > 0:
    logger.error(f"Found unexpected label(s) in results from Edge Endpoint: {unexpected_labels}. Expected: {EXPECTED_BINARY_LABELS}")
    sys.exit(1) # exit to avoid sending heartbeat

# Report heartbeat
# If all previous tests pass, send one image query to Groundlight Cloud, an alert will fire if the
# detector goes silent for too long
logger.info("Laptop edge canary seems to be online and functioning properly. Submitting hearbeat...")
heartbeat_frame = grabber.grab()
send_heartbeat(heartbeat_detector, heartbeat_frame)

grabber.release()