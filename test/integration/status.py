import time

import requests
from integration import LIVE_TEST_ENDPOINT

TEST_ENDPOINT = LIVE_TEST_ENDPOINT
MAX_WAIT_TIME_S = 60


def check_status_page():
    """Ensure that the edge-endpoint status page comes online."""
    start_time = time.time()
    final_exception = None
    while time.time() - start_time < MAX_WAIT_TIME_S:
        try:
            # verify=False is a no-op for http:// endpoints; needed for https:// endpoints
            # using the edge endpoint's self-signed certificate.
            status_response = requests.get(TEST_ENDPOINT + "/status", verify=False)
            status_response.raise_for_status()
            if status_response.status_code == 200:
                return
        except requests.RequestException as e:
            final_exception = e
            time.sleep(1)  # wait for 1 second before retrying
    raise Exception(
        f"Edge endpoint status page is not available after polling for {MAX_WAIT_TIME_S} seconds. {final_exception=}"
    )


if __name__ == "__main__":
    check_status_page()
