"""Set up the G4 e2e test detector and push edge config that pins it to NO_CLOUD.

`gl.edge.set_config` blocks until the inference deployment for this detector
reports Ready (or raises TimeoutError), so when this script returns
successfully the inference pod is up and serving.

Reads `GROUNDLIGHT_API_TOKEN` and `GROUNDLIGHT_ENDPOINT` from env. Diagnostic
output goes to stderr; the detector ID is the only thing on stdout so the
caller can capture it via `$()` in shell.
"""

import logging
import sys
import time

import requests
from groundlight import ExperimentalApi
from groundlight.edge import NO_CLOUD, EdgeEndpointConfig

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
logger = logging.getLogger(__name__)

DETECTOR_NAME = "g4-cicd-edge-test-cat"
DETECTOR_QUERY = "Is this a cat?"
TOTAL_TIMEOUT_SEC = 900  # cold-start g4dn pulls a GPU inference image + downloads model from S3
SET_CONFIG_ATTEMPT_TIMEOUT_SEC = 120  # per-attempt cap; transient hangs shouldn't burn the whole budget
RETRY_SLEEP_SEC = 5


def set_config_with_retry(gl: ExperimentalApi, config: EdgeEndpointConfig) -> None:
    """`gl.edge.set_config` polls /edge-detector-readiness with a 10s per-request
    timeout, and any single ReadTimeout/ConnectionError takes down the whole
    polling loop. Wrap with retry so a transient slow poll while the inference
    pod is warming up doesn't fail the test.
    """
    deadline = time.time() + TOTAL_TIMEOUT_SEC
    last_exc: Exception | None = None
    while time.time() < deadline:
        remaining = max(deadline - time.time(), 30)
        attempt = min(remaining, SET_CONFIG_ATTEMPT_TIMEOUT_SEC)
        try:
            gl.edge.set_config(config, timeout_sec=attempt)
            return
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
            last_exc = e
            logger.info("set_config transient failure (%s); retrying in %ds", type(e).__name__, RETRY_SLEEP_SEC)
            time.sleep(RETRY_SLEEP_SEC)
        except TimeoutError as e:
            last_exc = e
            logger.info("set_config attempt timed out; retrying (remaining: %ds)", int(deadline - time.time()))
    raise last_exc or TimeoutError(f"set_config did not converge within {TOTAL_TIMEOUT_SEC}s")


def main() -> None:
    gl = ExperimentalApi()

    detector = gl.get_or_create_detector(name=DETECTOR_NAME, query=DETECTOR_QUERY)
    logger.info("Detector ready: %s (%s)", detector.id, detector.name)

    config = EdgeEndpointConfig()
    config.add_detector(detector, NO_CLOUD)
    logger.info("Pushing edge config (NO_CLOUD) and waiting for inference pod ready...")
    set_config_with_retry(gl, config)
    logger.info("Inference deployment is Ready.")

    print(detector.id)


if __name__ == "__main__":
    main()
