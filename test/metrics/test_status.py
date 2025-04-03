import os
import time

import pytest
import requests

# Tests in this file require a live edge-endpoint server and GL Api token in order to run.
# Not ideal for unit-testing.
TEST_ENDPOINT = os.getenv("LIVE_TEST_ENDPOINT", "http://localhost:30101")
MAX_WAIT_TIME_S = 60


@pytest.mark.live
def test_status():
    """Ensure that the edge-endpoint status page comes online."""
    start_time = time.time()
    final_exception = None
    while time.time() - start_time < MAX_WAIT_TIME_S:
        try:
            status_response = requests.get(TEST_ENDPOINT + "/status")
            status_response.raise_for_status()
            if status_response.status_code == 200:
                return
        except requests.RequestException as e:
            final_exception = e
            time.sleep(1)  # wait for 1 second before retrying
    pytest.fail(
        f"Edge endpoint status page is not available after polling for {MAX_WAIT_TIME_S} seconds. {final_exception=}"
    )
