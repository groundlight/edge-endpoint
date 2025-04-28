import groundlight
import framegrab
import time
import logging
import os
import sys
import image_utils

from alerts import create_heartbeat_alert, send_heartbeat

NUM_IMAGE_QUERIES = 1000
MAX_EXPECTED_EDGE_INFERENCE_TIME_SEC = 0.4
TARGET_FRAME_WIDTH = 640

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S",
    # It seems one of framegrab's dependencies is overriding any logging config that we try to set here: See: https://github.com/groundlight/framegrab/pull/59
    # force=True fixes this
    force=True, 
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

create_heartbeat_alert(heartbeat_detector, 15)

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

confidences = []

logger.info(
    f'Starting laptop edge canary test. Submitting {NUM_IMAGE_QUERIES} image queries to {detector_id}...'
    )
edge_query_count = 0
cloud_query_count = 0
test_start_time = time.time()
for n in range(NUM_IMAGE_QUERIES):
    
    frame = grabber.grab()
    resized_frame = image_utils.resize_image(frame, TARGET_FRAME_WIDTH)
    
    inference_start = time.time()
    iq = gl.submit_image_query(
        detector=detector,
        image=resized_frame,
        human_review="DEFAULT",
        wait=0.0,
        confidence_threshold=0.75, # let's be conservative about escalation to keep inferences moving quickly
    )
    inference_end = time.time()
    inference_duration = inference_end - inference_start
    # logger.info(f'inference_duration: {inference_duration:.2f}')
    
    if inference_duration > MAX_EXPECTED_EDGE_INFERENCE_TIME_SEC:
        cloud_query_count +=1
        logger.warning(
            f'Image query {iq.id} finished in {inference_duration:.2f} second(s), which suggests it got a cloud answer rather than an edge answer. '
            f'Too many cloud inferences might slow this test down to the point of failure. Consider adding more labels to your detector ({detector_id}).'
            )
    else:
        edge_query_count += 1
    
    unique_labels.add(iq.result.label.value)
    confidences.append(iq.result.confidence)
    
test_end_time = time.time()
test_duration = test_end_time - test_start_time
query_rate = NUM_IMAGE_QUERIES / test_duration
logger.info(f'Processed {NUM_IMAGE_QUERIES} image queries in {test_duration:.2f} seconds at {query_rate:.2f} queries per second.')

# TODO should we have any expectations about average confidence?
average_confidence = sum(confidences) / len(confidences)
logger.info(f'Finished with an average confidence of {average_confidence:.2f}.')

# TODO should we have any expectations about how many queries go to the cloud?
logger.info(f'{cloud_query_count / NUM_IMAGE_QUERIES * 100:.2f}% of image queries escalated to the cloud.')

# Check that the query rate is sufficiently fast (edge speed)
# keep MINIMUM_EXPECTED_BINARY_QUERY_RATE on the conservative side to avoid alerting too much
# Queries might still escalate to cloud ML if unsure, which could slow things down.
MINIMUM_EXPECTED_BINARY_QUERY_RATE = 7.0 
if query_rate < MINIMUM_EXPECTED_BINARY_QUERY_RATE:
    logger.error(
        f"Edge Canary actual binary query rate is {query_rate}, less that expected minimum of {MINIMUM_EXPECTED_BINARY_QUERY_RATE}. "
        f"There might be something wrong with the Edge Endpoint, or your detector ({detector_id}) might need more labels to function properly."
        )
    sys.exit(1) # exit to avoid sending heartbeat

# Check that the received labels are valid
EXPECTED_BINARY_LABELS = set(["YES", "NO", "UNCLEAR"])
unexpected_labels = unique_labels - EXPECTED_BINARY_LABELS
if len(unexpected_labels) > 0:
    logger.error(f"Found unexpected label(s) in results from Edge Endpoint: {unexpected_labels}. Expected: {EXPECTED_BINARY_LABELS}")
    sys.exit(1) # exit to avoid sending heartbeat

# Report heartbeat
# If all previous tests pass, send one image query to Groundlight Cloud
# An alert will fire if the detector goes silent for too long
logger.info("Laptop edge canary seems to be online and functioning properly. Submitting heartbeat...")
heartbeat_frame = grabber.grab()
resized_heartbeat_frame = image_utils.resize_image(heartbeat_frame, TARGET_FRAME_WIDTH)
send_heartbeat(heartbeat_detector, resized_heartbeat_frame)

grabber.release()