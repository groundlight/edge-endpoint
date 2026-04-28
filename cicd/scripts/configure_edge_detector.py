"""Set up the G4 e2e test detector and push edge config that pins it to NO_CLOUD.

`gl.edge.set_config` blocks until the inference deployment for this detector
reports Ready (or raises TimeoutError), so when this script returns
successfully the inference pod is up and serving.

Reads `GROUNDLIGHT_API_TOKEN` and `GROUNDLIGHT_ENDPOINT` from env. Diagnostic
output goes to stderr; the detector ID is the only thing on stdout so the
caller can capture it via `$()` in shell.
"""

import sys

from groundlight import ExperimentalApi
from groundlight.edge import NO_CLOUD, EdgeEndpointConfig

DETECTOR_NAME = "g4-cicd-edge-test-cat"
DETECTOR_QUERY = "Is this a cat?"
SET_CONFIG_TIMEOUT_SEC = 900  # cold-start g4dn pulls a GPU inference image + downloads model from S3


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def main() -> None:
    gl = ExperimentalApi()

    detector = gl.get_or_create_detector(name=DETECTOR_NAME, query=DETECTOR_QUERY)
    log(f"Detector ready: {detector.id} ({detector.name})")

    config = EdgeEndpointConfig()
    config.add_detector(detector, NO_CLOUD)
    log("Pushing edge config (NO_CLOUD) and waiting for inference pod ready...")
    gl.edge.set_config(config, timeout_sec=SET_CONFIG_TIMEOUT_SEC)
    log("Inference deployment is Ready.")

    print(detector.id)


if __name__ == "__main__":
    main()
