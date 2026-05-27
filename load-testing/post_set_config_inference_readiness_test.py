"""
Reproduce intermittent 5xx errors immediately after gl.edge.set_config() reports ready.

Each trial clears the edge config, re-applies the detector (forcing a fresh inference pod
rollout), then fires inference requests with no delay and no SDK retries so transient
503s are not masked.
"""
import argparse
import time

from groundlight import ExperimentalApi, ApiException
from groundlight.edge import EdgeEndpointConfig, InferenceConfig, NO_CLOUD

import groundlight_helpers as glh
import image_helpers as imgh


def _edge_config_for_detector(detector, edge_inference_config: InferenceConfig) -> EdgeEndpointConfig:
    edge_config = EdgeEndpointConfig()
    edge_config.add_detector(detector, edge_inference_config)
    return edge_config


def _run_burst(gl: ExperimentalApi, detector, burst_size: int) -> list[dict]:
    """Submit burst_size image queries back-to-back; return failure records (may be empty)."""
    failures = []
    for i in range(burst_size):
        image, _, _ = imgh.generate_random_binary_image()
        try:
            gl.submit_image_query(detector, image, **glh.IQ_KWARGS_FOR_NO_ESCALATION)
        except ApiException as e:
            failures.append({
                "burst_index": i,
                "status": e.status,
                "reason": e.reason,
                "body": getattr(e, "body", None),
            })
    return failures


def run_trial(
    gl: ExperimentalApi,
    detector,
    *,
    burst_size: int,
    set_config_timeout_sec: float,
    edge_inference_config: InferenceConfig,
) -> dict:
    """One trial: clear config, set_config until ready, immediate inference burst."""
    gl.edge.set_config(EdgeEndpointConfig(), timeout_sec=set_config_timeout_sec)
    gl.edge.set_config(
        _edge_config_for_detector(detector, edge_inference_config),
        timeout_sec=set_config_timeout_sec,
    )
    set_config_finished_at = time.time()
    failures = _run_burst(gl, detector, burst_size)
    return {
        "set_config_finished_at": set_config_finished_at,
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Test for 5xx errors immediately after edge.set_config() reports all detectors ready. "
            "Retries are disabled so SDK retry logic cannot hide transient failures."
        ),
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=20,
        help="Number of clear-and-reconfigure cycles (default: 20).",
    )
    parser.add_argument(
        "--burst-size",
        type=int,
        default=10,
        help="Image queries to fire immediately after each set_config (default: 10).",
    )
    parser.add_argument(
        "--set-config-timeout-sec",
        type=float,
        default=900,
        help="Max seconds to wait per set_config call (default: 900).",
    )
    parser.add_argument(
        "--detector-mode",
        choices=["BINARY", "COUNT", "BOUNDING_BOX", "MULTI_CLASS"],
        default="BINARY",
        help="Detector mode to provision (default: BINARY).",
    )
    args = parser.parse_args()

    gl = ExperimentalApi()
    glh.error_if_endpoint_is_cloud(gl)
    glh.disable_all_retries(gl)
    gl_cloud = ExperimentalApi(endpoint=glh.CLOUD_ENDPOINT_PROD)

    detector = glh.provision_detector(
        gl_cloud,
        args.detector_mode,
        "Post Set Config Readiness Test",
        group_name="Edge Endpoint Load Testing",
    )

    print(
        f"Detector {detector.id} ({args.detector_mode}). "
        f"{args.trials} trials, {args.burst_size} immediate queries per trial. "
        "SDK retries disabled.\n"
    )

    trials_with_failures = 0
    total_failures = 0
    for trial in range(args.trials):
        result = run_trial(
            gl,
            detector,
            burst_size=args.burst_size,
            set_config_timeout_sec=args.set_config_timeout_sec,
            edge_inference_config=NO_CLOUD,
        )
        failures = result["failures"]
        if failures:
            trials_with_failures += 1
            total_failures += len(failures)
            print(f"Trial {trial + 1}/{args.trials}: {len(failures)} failure(s)")
            for f in failures:
                print(f"  burst[{f['burst_index']}] status={f['status']} reason={f['reason']}")
                if f["body"]:
                    print(f"    body={f['body'][:500]}")
        else:
            print(f"Trial {trial + 1}/{args.trials}: ok")

    print(
        f"\nSummary: {trials_with_failures}/{args.trials} trials had failures, "
        f"{total_failures} total failed requests."
    )
    if trials_with_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
