import time

from groundlight import Groundlight

duration_secs = 60
interval_secs = 1

detector_id = "det_2mIZTxUnJDhhUtJbUXavUevW15K"
img_path = "../../test/assets/cat.jpeg"

print(f"Config: duration_secs={duration_secs}, interval_secs={interval_secs}, conf_thresh will be set below")
print(f"Detector: {detector_id}")
print(f"Image path: {img_path}")

gl_cloud = Groundlight()
edge_endpoint = "http://localhost:30101"
gl_edge = Groundlight(endpoint=edge_endpoint)

print("Initialized Groundlight clients")
print(f"Edge endpoint: {edge_endpoint}")

conf_thresh = 1.0
print(f"Confidence threshold: {conf_thresh}")

num_queries = 10
total_time = 0
start_time = time.time()
print(f"Starting submission loop for {duration_secs}s with interval {interval_secs}s")

response_ids = []

last_query_time = start_time - 1.0
while time.time() - start_time < duration_secs:
    now = time.time()
    if now - last_query_time >= interval_secs:
        next_index = len(response_ids) + 1
        print(f"[{now - start_time:.2f}s] Submitting query #{next_index}")
        response = gl_edge.submit_image_query(
            detector=detector_id, image=img_path, wait=0, confidence_threshold=conf_thresh
        )
        response_ids.append(response.id)
        # print(f"[{now - start_time:.2f}s] Submitted: id={response['id']}")
        last_query_time = now
    else:
        sleep_time = interval_secs - (now - last_query_time)
        # print(f"[{now - start_time:.2f}s] Sleeping {sleep_time:.3f}s to respect interval")
        time.sleep(sleep_time)

elapsed = time.time() - start_time
print(f"Finished submissions: total submitted={len(response_ids)} in {elapsed:.2f}s")

input("Next will verify that responses are present in cloud. Press Enter to continue...")

print("Verifying that responses are present in cloud...")
response_is_in_cloud = [False] * len(response_ids)
for i, response_id in enumerate(response_ids):
    try:
        gl_cloud.get_image_query(response_id)
        response_is_in_cloud[i] = True
    except Exception:
        pass

if not all(response_is_in_cloud):
    missing = len(response_ids) - sum(response_is_in_cloud)
    print(f"There are {missing} responses not in cloud")
else:
    print("All responses are in cloud")
