import groundlight
import framegrab
import time
import math

NUM_IMAGE_QUERIES = 1000

gl = groundlight.Groundlight()

detector = gl.get_detector("det_2sxWe4bhmSjcAeqNk2R9wc2xaIb")

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

load_test_start_time = time.time()
for n in range(NUM_IMAGE_QUERIES):
    
    frame = grabber.grab()
    
    inf_start = time.time()
    iq = gl.ask_ml(detector, frame)
    inf_end = time.time()
    inference_time = inf_end - inf_start
    
    label = iq.result.label
    
    confidence_str = f'{math.floor(iq.result.confidence * 100)}%'
    source = iq.result.source
    text = f'{n}/{NUM_IMAGE_QUERIES} - {label} - {confidence_str} - {inference_time:.2f} seconds - {source}'
        
    print(text)
        
load_test_end_time = time.time()
load_test_time = load_test_end_time - load_test_start_time
query_rate = NUM_IMAGE_QUERIES / load_test_time
print(f'Processed {NUM_IMAGE_QUERIES} image queries in {load_test_time:.2f} seconds. {query_rate:.2f} queries per second.')

grabber.release()