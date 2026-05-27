"""Top-level orchestration: load → validate → for each run: provision +
push edge config + spawn workers + monitor + summarize → cleanup.
"""

import argparse
import atexit
import logging
import multiprocessing as mp
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from groundlight import ExperimentalApi
from system_helpers import SystemMonitor

from app_benchmark import lenses, network, report
from app_benchmark.config import (
    BboxToBinaryLens,
    BenchmarkConfig,
    ConfigError,
    SingleBboxLens,
    SingleBinaryLens,
    load_config,
    num_runs,
)
from app_benchmark.detectors import DetectorManager, ResolvedRun, StageDetector
from app_benchmark.host_check import HostNotCleanError, ensure_host_clean

logger = logging.getLogger("app_benchmark")


def _resolve_output_dir(template: str, run_name: str) -> Path:
    """Substitute `{name}` and `{ts}` placeholders in an output_dir template."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path(template.format(name=run_name, ts=ts))


def _lens_n_for_run(cfg: BenchmarkConfig, run_index: int) -> dict[str, int]:
    """Pick the `n` value at position `run_index` from every lens that
    declares an `n` list. Lenses without `n` are absent from the result."""
    out: dict[str, int] = {}
    for lens in cfg.lenses:
        if hasattr(lens, "n"):
            out[lens.name] = lens.n[run_index]
    return out


def _lens_cameras_for_run(cfg: BenchmarkConfig, run_index: int) -> dict[str, int]:
    """Resolve every lens's camera count for this run.

    Scalar `cameras` resolves to the same value across every run; list
    `cameras` picks element `run_index`. Every lens is present in the
    result (unlike `_lens_n_for_run`, which omits lenses without `n`),
    so worker spawning has a single source of truth for the count.
    """
    out: dict[str, int] = {}
    for lens in cfg.lenses:
        if isinstance(lens.cameras, list):
            out[lens.name] = lens.cameras[run_index]
        else:
            out[lens.name] = lens.cameras
    return out


def _build_worker_args(
    lens,
    sds: list[StageDetector],
    n: int | None,
    cfg: BenchmarkConfig,
    edge_url: str,
    log_file: str,
    duration_seconds: float,
    worker_number: int,
    camera: int,
):
    """Build the (target_fn, kwargs) pair for one camera process.

    Resolves per-lens overrides (image_size, target_fps) against globals
    and picks the right runner function plus the right detector IDs from
    `sds` (the stage detectors for this lens).

    Args:
        lens: A LensSpec subtype (SingleBinaryLens, SingleBboxLens, or
            BboxToBinaryLens).
        sds: Stage detectors for THIS lens (typically 1 or 2 entries).
        n: This run's `n` value for the lens, or None if the lens has
            no `n` (single_binary case).
        cfg: Full benchmark config — used to resolve global defaults.
        edge_url: Edge endpoint URL the worker should hit.
        log_file: JSONL log path the worker should append to.
        duration_seconds: Total worker lifetime including warmup.
        worker_number: Global worker index (across all lenses + cameras).
        camera: Per-lens camera index.

    Returns:
        (target_fn, kwargs_dict) suitable for multiprocessing.Process.
    """
    image_size = tuple(lens.image_size if lens.image_size is not None else cfg.globals_.image_size)
    target_fps = lens.target_fps if lens.target_fps is not None else cfg.globals_.target_fps
    common = dict(
        worker_number=worker_number, camera=camera, lens_name=lens.name,
        edge_url=edge_url, image_size=image_size, target_fps=target_fps,
        duration_seconds=duration_seconds, log_file=log_file,
    )
    if isinstance(lens, SingleBinaryLens):
        single = next(sd for sd in sds if sd.stage == "single")
        return lenses.run_single_binary, {**common, "detector_id": single.detector_id}
    if isinstance(lens, SingleBboxLens):
        single = next(sd for sd in sds if sd.stage == "single")
        return lenses.run_single_bbox, {**common, "detector_id": single.detector_id, "n": n}
    if isinstance(lens, BboxToBinaryLens):
        bbox = next(sd for sd in sds if sd.stage == "bbox")
        binary = next(sd for sd in sds if sd.stage == "binary")
        return lenses.run_bbox_to_binary, {
            **common,
            "bbox_detector_id": bbox.detector_id,
            "binary_detector_id": binary.detector_id,
            "n": n,
        }
    raise RuntimeError(f"unknown lens type: {type(lens).__name__}")


def _spawn_lens_workers(
    cfg: BenchmarkConfig,
    run: ResolvedRun,
    edge_url: str,
    run_dir: Path,
    duration_seconds: float,
) -> list[mp.Process]:
    """Start one Process per (lens × camera) and return them.

    Workers are started in lens-config order; worker_number increments
    monotonically. Each worker writes to its own `camera_{lens}_{N}.log`
    in `run_dir` — no shared writer, so no inter-process race on the log.

    Args:
        cfg: Benchmark config (for lens list and overrides).
        run: ResolvedRun providing lens_n and the shared stage_detectors.
        edge_url: Edge endpoint URL passed into each worker.
        run_dir: Per-run output directory; per-camera log files live here.
        duration_seconds: How long each worker should run before exiting.

    Returns:
        List of started Process objects (already `.start()`ed).
    """
    by_lens: dict[str, list[StageDetector]] = {}
    for sd in run.stage_detectors:
        by_lens.setdefault(sd.lens_name, []).append(sd)
    procs: list[mp.Process] = []
    worker_number = 0
    for lens in cfg.lenses:
        sds = by_lens[lens.name]
        cameras_this_run = run.lens_cameras[lens.name]
        for cam_idx in range(cameras_this_run):
            log_path = run_dir / f"camera_{lens.name}_{cam_idx}.log"
            target, kwargs = _build_worker_args(
                lens, sds, run.lens_n.get(lens.name), cfg, edge_url,
                str(log_path), duration_seconds, worker_number, cam_idx,
            )
            p = mp.Process(target=target, kwargs=kwargs, name=f"{lens.name}_cam{cam_idx}")
            p.start()
            procs.append(p)
            worker_number += 1
    return procs


def _join_with_grace(procs: list[mp.Process], timeout_s: float) -> list[dict]:
    """Wait for every worker process to exit (with a hard cap), then
    collect non-zero exit codes as failures for the report.

    Args:
        procs: Worker processes to join.
        timeout_s: Hard total budget across all joins. Any process still
            alive at the deadline is `.terminate()`'d.

    Returns:
        List of {"name": process_name, "exitcode": code} dicts for every
        worker that exited with a non-zero (or None) exit code. Surfaced
        as worker_failures in summary.json / summary.md.
    """
    deadline = time.time() + timeout_s
    for p in procs:
        remaining = max(0.0, deadline - time.time())
        p.join(remaining)
    for p in procs:
        if p.is_alive():
            logger.warning("worker %s still alive after timeout; terminating", p.name)
            p.terminate()
            p.join(5)
    failures: list[dict] = []
    for p in procs:
        code = p.exitcode
        if code is None or code != 0:
            logger.error("worker %s exited with code %s", p.name, code)
            failures.append({"name": p.name, "exitcode": code})
    return failures


def _run_one(
    cfg: BenchmarkConfig,
    run: ResolvedRun,
    out_root: Path,
) -> dict:
    """Execute one run end-to-end (warmup + measurement window + cleanup).

    Workers are spawned for `warmup + duration` seconds. The
    measurement window starts AFTER the warmup sleep and is fixed at
    `[main_start_ts, main_start_ts + duration)` — any request landing
    after that boundary is excluded from the summary.

    Args:
        cfg: Benchmark config.
        run: ResolvedRun for this iteration; carries the per-lens `n`
            and the shared stage_detectors.
        out_root: Top-level output directory; this run writes into
            `out_root/run_NN/`.

    Returns:
        The per-run summary dict produced by report.write_run_artifacts,
        which also wrote `run_NN/summary.json` and the per-run plots.
    """
    run_dir = out_root / f"run_{run.run_index:02d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    system_log = run_dir / "system.log"

    duration = float(cfg.globals_.duration_seconds)
    warmup = float(cfg.globals_.warmup_seconds)

    monitor = SystemMonitor(
        str(system_log),
        sample_interval=1.0 / cfg.monitoring.sample_hz,
        endpoint=cfg.run.edge_endpoint_url,
    )
    monitor.start()

    try:
        # Workers run for warmup + duration. Main thread sleeps `warmup`,
        # then records main_start_ts which the report uses as the
        # post-warmup window start.
        worker_lifetime = warmup + duration
        procs = _spawn_lens_workers(
            cfg, run, cfg.run.edge_endpoint_url, run_dir, worker_lifetime,
        )
        logger.info("[run %d] %d worker(s) spawned; warmup %.0fs, main %.0fs",
                    run.run_index, len(procs), warmup, duration)
        if warmup > 0:
            time.sleep(warmup)
        main_start_ts = time.time()
        # Intended measurement window — fixed by config, not by wall-clock.
        # Any in-flight or grace-period activity past main_end_ts is excluded.
        main_end_ts = main_start_ts + duration
        time.sleep(duration)
        worker_failures = _join_with_grace(procs, timeout_s=30.0)
    finally:
        monitor.stop()

    run_meta = {
        "run_index": run.run_index,
        "lens_n": run.lens_n,
        "lens_cameras": run.lens_cameras,
        "lenses": [
            {
                "name": l.name,
                "type": l.type,
                # Per-run camera count, not the raw config field — so the
                # report's per-run table iterates over exactly the cameras
                # that ran in this iteration (relevant when `cameras` is a
                # ramp list).
                "cameras": run.lens_cameras[l.name],
                "target_fps": (l.target_fps if l.target_fps is not None
                               else cfg.globals_.target_fps),
                "image_size": list(l.image_size if l.image_size is not None
                                   else cfg.globals_.image_size),
            }
            for l in cfg.lenses
        ],
        "duration_seconds": cfg.globals_.duration_seconds,
        "warmup_seconds": cfg.globals_.warmup_seconds,
        "main_start_ts": main_start_ts,
        "main_end_ts": main_end_ts,
        "worker_failures": worker_failures,
    }
    return report.write_run_artifacts(
        run_dir, run_meta,
        main_start_ts=main_start_ts, main_end_ts=main_end_ts,
    )


def main(argv: list[str] | None = None) -> int:
    """Entry point for `python -m app_benchmark <config.yaml>`.

    Performs (in order):
      1. Parse args, load + validate the YAML config.
      2. Measure an ICMP ping baseline to the edge (skipped for loopback).
      3. Refuse if the edge already has detectors loaded
         (`refuse_if_host_not_clean: true`).
      4. Snapshot pre-run edge config; register atexit cleanup.
      5. Provision every detector once and push edge config once.
      6. Run each n-step sweep iteration via `_run_one`.
      7. Write the consolidated top-level summary.md + summary.json with
         cross-run combined plots.

    Args:
        argv: Optional CLI args list (None means use sys.argv).

    Returns:
        Process exit code: 0 success, 1 unhandled failure during runs,
        2 config or env error, 3 host-clean check failed,
        130 KeyboardInterrupt.
    """
    parser = argparse.ArgumentParser(description="Edge-endpoint application benchmarking harness.")
    parser.add_argument("config", help="Path to benchmark YAML config.")
    parser.add_argument("--no-cleanup", action="store_true",
                        help="Skip detector deletion + edge-config restore at end (debug only).")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if not os.environ.get("GROUNDLIGHT_API_TOKEN"):
        print("ERROR: GROUNDLIGHT_API_TOKEN env var is not set "
              "(SDK reads it directly).", file=sys.stderr)
        return 2

    out_root = _resolve_output_dir(cfg.run.output_dir, cfg.run.name)
    out_root.mkdir(parents=True, exist_ok=True)
    logger.info("output dir: %s", out_root)
    started_at_iso = datetime.now(timezone.utc).isoformat()

    edge_host = network.host_from_url(cfg.run.edge_endpoint_url)
    network_baseline = network.measure(edge_host)
    network_baseline_text = network.format_summary(network_baseline, edge_host)
    logger.info("network ping baseline: %s", network_baseline_text)

    gl_cloud = ExperimentalApi(endpoint=cfg.run.cloud_endpoint)
    gl_edge = ExperimentalApi(endpoint=cfg.run.edge_endpoint_url)

    try:
        ensure_host_clean(gl_edge, allow=not cfg.run.refuse_if_host_not_clean)
    except HostNotCleanError as exc:
        logger.error("host check failed: %s", exc)
        return 3

    dm = DetectorManager(cfg, gl_cloud, gl_edge)
    dm.snapshot_edge_config()

    def _cleanup() -> None:
        if args.no_cleanup:
            logger.warning("--no-cleanup: skipping detector deletion + edge-config restore")
            return
        dm.restore_edge_config()
        deleted, failed = dm.delete_all()
        logger.info("cleanup: deleted=%d failed=%d", deleted, failed)
    atexit.register(_cleanup)

    n_runs = num_runs(cfg)
    logger.info("expanding to %d run(s)", n_runs)

    summaries: list[dict] = []
    try:
        logger.info("provisioning detectors (one-shot, reused across all runs)")
        stage_detectors = dm.provision_all()
        logger.info("pushing edge config (%d detector(s))", len(stage_detectors))
        dm.push_edge_config(stage_detectors)
        for i in range(n_runs):
            lens_n = _lens_n_for_run(cfg, i)
            lens_cameras = _lens_cameras_for_run(cfg, i)
            logger.info("[run %d/%d] lens_n=%s lens_cameras=%s", i + 1, n_runs, lens_n, lens_cameras)
            run = ResolvedRun(
                run_index=i, lens_n=lens_n, lens_cameras=lens_cameras,
                stage_detectors=stage_detectors,
            )
            summaries.append(_run_one(cfg, run, out_root))
    except KeyboardInterrupt:
        logger.warning("interrupted; running cleanup via atexit")
        return 130
    except Exception:
        logger.exception("benchmark run failed")
        return 1

    benchmark_meta = {
        "name": cfg.run.name,
        "started_at": started_at_iso,
        "edge_endpoint_url": cfg.run.edge_endpoint_url,
        "config": {
            "image_size": list(cfg.globals_.image_size),
            "target_fps": cfg.globals_.target_fps,
            "duration_seconds": cfg.globals_.duration_seconds,
            "warmup_seconds": cfg.globals_.warmup_seconds,
        },
        "lenses": report.summarize_lenses_config(cfg, stage_detectors),
    }
    report.write_top_level(
        out_root, summaries,
        benchmark_meta=benchmark_meta,
        network_baseline=network_baseline,
        network_baseline_text=network_baseline_text,
    )
    logger.info("done; results in %s", out_root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
