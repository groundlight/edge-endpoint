import groundlight
import framegrab
import time
import logging

from alerts import create_hearbeat_alert, send_heartbeat

NUM_IMAGE_QUERIES = 1000

logger = logging.getLogger(__name__)

gl = groundlight.Groundlight()

detector_id = "det_2sxWe4bhmSjcAeqNk2R9wc2xaIb"
detector = gl.get_detector(detector_id)

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

logger.info('Starting canary load test...')
unique_labels = set()
load_test_start_time = time.time()
for n in range(NUM_IMAGE_QUERIES):
    
    frame = grabber.grab()
    
    inf_start = time.time()
    iq = gl.ask_ml(detector, frame)
    inf_end = time.time()
    inference_time = inf_end - inf_start
    
    unique_labels.add(iq.result.label.value)
    
load_test_end_time = time.time()
load_test_time = load_test_end_time - load_test_start_time
query_rate = NUM_IMAGE_QUERIES / load_test_time
logger.info(f'Processed {NUM_IMAGE_QUERIES} image queries in {load_test_time:.2f} seconds. {query_rate:.2f} queries per second.')

# Check that the query rate is sufficiently fast (edge speed)
MINIMUM_EXPECTED_BINARY_QUERY_RATE = 5.0 # this is a little conservative to avoid alerting too much
if query_rate < MINIMUM_EXPECTED_BINARY_QUERY_RATE:
    # TODO change this to be a pager duty message
    logger.error(f"Edge Canary actual binary query rate is {query_rate}, less that expected minimum of {MINIMUM_EXPECTED_BINARY_QUERY_RATE}.")

# check that the results
EXPECTED_BINARY_LABELS = set(["YES", "NO", "UNSURE"])
unexpected_labels = unique_labels - EXPECTED_BINARY_LABELS
if len(unexpected_labels) > 0:
     # TODO change this to be a pager duty message
    logger.error(f"Found unexpected label(s) in results from Edge Endpoint: {unexpected_labels}")

# Report heartbeat
# If all the previous tests pass, send one image query to Groundlight Cloud, an alert will fire if the
# detector goes silent for too long
heartbeat_frame = grabber.grab()
send_heartbeat(heartbeat_detector, heartbeat_frame)

grabber.release()