from groundlight import Groundlight

UNDEPLOYED = "det_2yNfqQGo19NCxOoG6tCOQNqFQRw"
DEFAULT = "det_2mIZTxUnJDhhUtJbUXavUevW15K"
EDGE_ANSWERS = "det_2yNfwyb7xPjXB1fSBXCmy9IwGqx"
NO_CLOUD = "det_2yNfwEEn2dwAtgkv4ejhEj6LCQo"

ENDPOINT = "http://localhost:30107"
IMG_PATH = "test/assets/dog.jpeg"
NUM_QUERIES = 5

gl = Groundlight(endpoint=ENDPOINT)


def submit_to_detector(det_id, img_path, conf_thresh) -> list[str]:
    iq_ids = []
    for _ in range(NUM_QUERIES):
        iq = gl.submit_image_query(detector=det_id, image=img_path, wait=0, confidence_threshold=conf_thresh)
        iq_ids.append(iq.id)
    return iq_ids


def are_iqs_in_cloud(iq_ids) -> list[bool]:
    results = []
    for id in iq_ids:
        try:
            gl.get_image_query(id)
            results.append(True)
        except Exception as e:
            print(f"Got exception while checking IQ in cloud: {e}")
            results.append(False)
    return results


def verify_iqs_in_cloud(iq_ids) -> bool:
    results = are_iqs_in_cloud(iq_ids)
    if not all(results):
        return False
    return True


def verify_iqs_not_in_cloud(iq_ids) -> bool:
    results = are_iqs_in_cloud(iq_ids)
    if any(results):
        return False
    return True


def submit_to_undeployed() -> list[str]:
    iq_ids = submit_to_detector(UNDEPLOYED, IMG_PATH, 0.5)
    return iq_ids


def submit_to_default() -> tuple[list[str], list[str]]:
    iq_ids_low_conf = submit_to_detector(DEFAULT, IMG_PATH, 0.5)
    iq_ids_high_conf = submit_to_detector(DEFAULT, IMG_PATH, 1.0)

    return iq_ids_low_conf, iq_ids_high_conf


def submit_to_edge_answers() -> tuple[list[str], list[str]]:
    iq_ids_low_conf = submit_to_detector(EDGE_ANSWERS, IMG_PATH, 0.5)
    iq_ids_high_conf = submit_to_detector(EDGE_ANSWERS, IMG_PATH, 1.0)

    return iq_ids_low_conf, iq_ids_high_conf


def submit_to_no_cloud() -> tuple[list[str], list[str]]:
    iq_ids_low_conf = submit_to_detector(DEFAULT, IMG_PATH, 0.5)
    iq_ids_high_conf = submit_to_detector(DEFAULT, IMG_PATH, 1.0)

    return iq_ids_low_conf, iq_ids_high_conf


undeployed_ids = submit_to_undeployed()
default_ids_low_conf, default_ids_high_conf = submit_to_default()
edge_answers_ids_low_conf, edge_answers_ids_high_conf = submit_to_edge_answers()
no_cloud_ids_low_conf, no_cloud_ids_high_conf = submit_to_no_cloud()

print("Type anything and hit ENTER to continue.")
input()

undeployed_result = verify_iqs_in_cloud(undeployed_ids)
if not undeployed_result:
    print("Expected all queries to be in cloud for undeployed detector, but they aren't.")

default_low_conf_result = verify_iqs_not_in_cloud(default_ids_low_conf)
default_high_conf_result = verify_iqs_in_cloud(default_ids_high_conf)
if not default_low_conf_result:
    print("Expected none of the 0.5 conf queries to be in cloud for default detector, but at least one is.")
if not default_high_conf_result:
    print("Expected all of the 1.0 conf queries to be in cloud for default detector, but they aren't.")

edge_answers_low_conf_result = verify_iqs_not_in_cloud(edge_answers_ids_low_conf)
edge_answers_high_conf_result = verify_iqs_in_cloud(edge_answers_ids_high_conf)
if not edge_answers_low_conf_result:
    print("Expected none of the 0.5 conf queries to be in cloud for edge_answers detector, but at least one is.")
if not edge_answers_high_conf_result:
    print("Expected all of the 1.0 conf queries to be in cloud for edge_answers detector, but they aren't.")

no_cloud_low_conf_result = verify_iqs_not_in_cloud(no_cloud_ids_low_conf)
no_cloud_high_conf_result = verify_iqs_not_in_cloud(no_cloud_ids_high_conf)
if not no_cloud_low_conf_result:
    print("Expected none of the 0.5 conf queries to be in cloud for no_cloud detector, but at least one is.")
if not no_cloud_high_conf_result:
    print("Expected none of the 1.0 conf queries to be in cloud for no_cloud detector, but at least one is.")
