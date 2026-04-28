"""Submit one image query to the configured G4 detector and assert the answer
came from edge inference (not a cloud fallback).

The edge endpoint sets `metadata["edge_result"]` on responses it answered
itself; cloud-fallback responses do not have that field.
"""

import argparse
import sys

from groundlight import ExperimentalApi

IMAGE_PATH = "test/assets/cat.jpeg"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--detector-id", required=True)
    args = parser.parse_args()

    gl = ExperimentalApi()
    detector = gl.get_detector(args.detector_id)

    iq = gl.submit_image_query(
        detector=detector,
        image=IMAGE_PATH,
        confidence_threshold=0.5,
    )
    print(f"IQ {iq.id}: label={iq.result.label} confidence={iq.result.confidence}")
    print(f"Metadata: {iq.metadata}")

    if iq.metadata is None or "edge_result" not in iq.metadata:
        sys.exit(f"FAIL: expected 'edge_result' in metadata, got {iq.metadata}")

    print("PASS: image query was answered by edge inference")


if __name__ == "__main__":
    main()
