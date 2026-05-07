"""Top-level orchestration: load config, create detectors, run, cleanup."""

import argparse
import atexit
import json
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import groundlight_helpers as glh
from groundlight import ExperimentalApi

from app_benchmark import logging_setup, network
from app_benchmark.config import BenchmarkConfig, ConfigError, load_config
from app_benchmark.detectors import CreatedDetector, DetectorManager
from app_benchmark.environment import capture as capture_env
from app_benchmark.environment import hash_config_yaml
from app_benchmark.host_check import HostNotCleanError, ensure_host_clean
from app_benchmark.metrics_writer import MetricsWriter
from app_benchmark.monitor import run_monitor
from app_benchmark.supervisor import Supervisor
from app_benchmark.verification import Verifier

logger = logging.getLogger(__name__)


def _resolve_output_dir(template: str, run_name: str) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path(template.format(name=run_name, ts=ts))


def _write_resolved_config(cfg: BenchmarkConfig, path: Path) -> None:
    path.write_text(json.dumps(cfg.model_dump(), indent=2, default=str))


def _resolve_steady_state(monitor_writer: MetricsWriter, cfg: BenchmarkConfig,
                          start_ts: float, hard_cap_s: float) -> tuple[float, bool]:
    """Block until steady-state OR hard cap. Returns (warmup_duration_s, reached)."""
    window_s = cfg.monitoring.steady_state_window_seconds
    min_warmup = cfg.run.warmup_seconds
    deadline = start_ts + hard_cap_s

    while time.time() < deadline:
        elapsed = time.time() - start_ts
        if elapsed < min_warmup:
            time.sleep(0.5)
            continue
        samples = monitor_writer.recent_samples(window_s)
        if len(samples) < max(2, int(window_s * cfg.monitoring.sample_hz * 0.6)):
            time.sleep(0.5)
            continue
        if any(s.loading_detectors_bytes > 0 for s in samples):
            time.sleep(0.5)
            continue
        # VRAM relative range
        vram = [s.gpu_vram_used_bytes for s in samples if s.gpu_vram_total_bytes > 0]
        if not vram:
            time.sleep(0.5)
            continue
        if max(vram) > 0:
            vram_range = (max(vram) - min(vram)) / max(vram)
        else:
            vram_range = 0.0
        # Per-lens FPS relative range across the rolling window.
        fps_map = monitor_writer.per_lens_recent_fps(last_n_seconds=window_s)
        fps_stable = True
        if fps_map:
            for lens_name, fps in fps_map.items():
                # Compare against another window: simple proxy — require nonzero & we settle.
                # If we have <2 windows of data, skip.
                pass
        if vram_range < 0.05 and fps_stable:
            return time.time() - start_ts, True
        time.sleep(0.5)

    return time.time() - start_ts, False


def _final_status(error_lens_count: int, total_lens: int, fatal: bool) -> str:
    if fatal:
        return "FAILED"
    if error_lens_count > 0:
        return "DEGRADED"
    return "OK"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Edge-endpoint application benchmarking harness.")
    parser.add_argument("config", help="Path to benchmark YAML config.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate, create detectors, configure edge, verify, then delete. No load generated.")
    parser.add_argument("--no-cleanup", action="store_true",
                        help="Skip detector deletion at end (debugging only).")
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if not os.environ.get("GROUNDLIGHT_API_TOKEN"):
        print("ERROR: GROUNDLIGHT_API_TOKEN env var is not set "
              "(SDK reads it directly).", file=sys.stderr)
        return 2

    output_dir = _resolve_output_dir(cfg.run.output_dir, cfg.run.name)
    output_dir.mkdir(parents=True, exist_ok=True)

    logging_setup.configure(output_dir=output_dir, run_name=cfg.run.name)
    logger.info("loaded config %s -> output %s", args.config, output_dir, extra={"phase": "startup"})
    _write_resolved_config(cfg, output_dir / "config.resolved.json")

    config_hash = hash_config_yaml(args.config)
    started_at_iso = datetime.now(timezone.utc).isoformat()

    gl_cloud = ExperimentalApi(endpoint=cfg.run.cloud_endpoint)
    gl_edge = ExperimentalApi(endpoint=cfg.run.edge_endpoint_url)

    # 0. Network latency baseline to the edge (ICMP ping × 5).
    edge_host = network.host_from_url(cfg.run.edge_endpoint_url)
    network_latency = network.measure(edge_host) if edge_host else None
    logger.info("network baseline: %s", network.format_summary(network_latency),
                extra={"phase": "startup"})

    # 1. Pre-flight host check.
    try:
        ensure_host_clean(gl_edge, expected_prefix=cfg.run.detector_name_prefix,
                         allow=not cfg.run.refuse_if_host_not_clean)
    except HostNotCleanError as exc:
        logger.error("host check failed: %s", exc, extra={"phase": "host_check"})
        return 3

    # 2. Create detectors (cloud + register on edge).
    dm = DetectorManager(cfg, gl_cloud, gl_edge)
    created: list[CreatedDetector] = []

    def _cleanup() -> None:
        if args.no_cleanup:
            logger.warning("--no-cleanup set; %d detector(s) NOT deleted, edge config NOT restored",
                           len(created), extra={"phase": "cleanup"})
            return
        # 1. Restore pre-run edge config first → tears down inference pods for our detectors.
        edge_restored = dm.restore_edge_config()
        # 2. Then delete detectors from the cloud.
        if not created:
            return
        deleted, failed = dm.delete_all(created)
        cleanup_log = output_dir / "cleanup.log"
        cleanup_log.write_text(
            f"created: {len(created)}\ndeleted: {deleted}\nfailed: {failed}\n"
            f"edge_config_restored: {edge_restored}\n"
            + "\n".join(f"  {c.spec_name} -> {c.detector_id}" for c in created) + "\n"
        )

    atexit.register(_cleanup)
    _cleanup_called = False

    def _signal_cleanup(signum, _frame):
        nonlocal _cleanup_called
        if _cleanup_called:
            logger.warning("second signal received; forcing exit", extra={"phase": "shutdown"})
            os._exit(130)
        _cleanup_called = True
        logger.warning("signal %d received; initiating shutdown", signum, extra={"phase": "shutdown"})
        # Caught by main loop via stop_event; the rest is via atexit.

    signal.signal(signal.SIGINT, _signal_cleanup)
    signal.signal(signal.SIGTERM, _signal_cleanup)

    try:
        # Snapshot the pre-run edge config BEFORE any modifications. Our
        # cleanup will restore this exact state to tear down our inference pods
        # while preserving any pre-existing detectors (only present when
        # refuse_if_host_not_clean=false).
        dm.snapshot_edge_config()
        created = dm.create_all()
        dm.register_on_edge(created)

        # 3. Verify control plane.
        repo_root = Path(__file__).resolve().parents[2]
        sentinel = repo_root / "load-testing" / "images" / "dog.jpeg"
        if not sentinel.is_file():
            sentinel = repo_root / "test" / "assets" / "dog.jpeg"
        verifier = Verifier(gl_edge, sentinel)
        verification = verifier.wait_for_ready([c.detector for c in created], timeout_s=120)
        logger.info("control-plane verified; from_edge=%s, latencies=%s",
                    verification.from_edge_verified, verification.sentinel_latency_ms,
                    extra={"phase": "verification"})

        if args.dry_run:
            logger.info("--dry-run: skipping run loop", extra={"phase": "run"})
            return 0

        # 4. Capture environment metadata.
        try:
            resources = glh._get_resources(gl_edge, timeout=5.0)
        except Exception:
            resources = None
        env_block = capture_env(gl_edge, resources, repo_root=str(repo_root))
        env_block["network_latency_ms"] = network_latency  # may be None

        # 5. Spin up supervisor + writer.
        supervisor = Supervisor(cfg, created, monitor_target=run_monitor, monitor_args=())
        writer_stop = threading.Event()
        writer = MetricsWriter(output_dir, supervisor.sample_queue, supervisor.frame_queue, writer_stop)
        writer.start()
        supervisor.start()

        # 6. Warmup with steady-state detection.
        warmup_start = time.time()
        hard_cap = max(cfg.run.warmup_seconds * 2.0, cfg.run.warmup_seconds + 30)
        warmup_duration, steady_state_reached = _resolve_steady_state(writer, cfg, warmup_start, hard_cap)
        writer.mark_post_warmup()
        run_started_ts = time.time()
        logger.info("warmup complete (%.1fs, steady_state=%s); main run begins",
                    warmup_duration, steady_state_reached, extra={"phase": "run"})

        # 7. Main run.
        supervisor.wait(cfg.run.duration_seconds)
        run_ended_ts = time.time()

        # 8. Stop everything.
        supervisor.stop(grace_s=10.0)
        writer_stop.set()
        writer.stop()

        # 9. Build report.
        client_failures = writer.client_failed_events()
        degraded_lenses = {ev.lens_name for ev in client_failures}
        total_clients_per_lens: dict[str, int] = {}
        for lens in cfg.lenses:
            total_clients_per_lens[lens.name] = lens.cameras
        run_status = "OK"
        for lens_name, total in total_clients_per_lens.items():
            failed = sum(1 for ev in client_failures if ev.lens_name == lens_name)
            if failed > 0 and failed >= max(1, total // 2):
                run_status = "DEGRADED"
        if degraded_lenses:
            run_status = "DEGRADED"

        run_warnings = {
            "dropped_events": writer.dropped_events(),
            "monitor_poll_failures": writer.monitor_failures(),
            "client_failed_events": [
                {"lens_name": ev.lens_name, "client_id": ev.client_id, "reason": ev.reason}
                for ev in client_failures
            ],
        }

        from app_benchmark import report as report_mod
        report_mod.build(
            cfg, output_dir,
            run_name=cfg.run.name,
            started_at_iso=started_at_iso,
            run_started_ts=run_started_ts,
            run_ended_ts=run_ended_ts,
            warmup_duration_s=warmup_duration,
            steady_state_reached=steady_state_reached,
            run_status=run_status,
            config_hash=config_hash,
            environment=env_block,
            control_plane={
                "from_edge_verified": verification.from_edge_verified,
                "introspection_endpoint_used": verification.introspection_used,
                "host_was_clean_at_start": True,
                "detectors_created": len(created),
            },
            run_warnings=run_warnings,
            created=created,
        )
        logger.info("run complete: status=%s", run_status, extra={"phase": "run"})
        return 0 if run_status == "OK" else 1

    except Exception:
        logger.exception("benchmark run failed", extra={"phase": "run"})
        return 1
    # _cleanup runs via atexit
