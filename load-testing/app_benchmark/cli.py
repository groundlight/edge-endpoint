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


def _lens_objects_for_run(cfg: BenchmarkConfig, run_index: int) -> dict[str, int]:
    """Pick the `objects` value at position `run_index` from every lens
    that declares an `objects` field.

    Scalar values resolve to the same value across every run; list
    values pick element `run_index`. Lenses without `objects` (e.g.
    single_binary) are absent from the result.
    """
    out: dict[str, int] = {}
    for lens in cfg.lenses:
        if hasattr(lens, "objects"):
            if isinstance(lens.objects, list):
                out[lens.name] = lens.objects[run_index]
            else:
                out[lens.name] = lens.objects
    return out


def _lens_cameras_for_run(cfg: BenchmarkConfig, run_index: int) -> dict[str, int]:
    """Resolve every lens's camera count for this run.

    Scalar `cameras` resolves to the same value across every run; list
    `cameras` picks element `run_index`. Every lens is present in the
    result (unlike `_lens_objects_for_run`, which omits lenses without
    `objects`), so worker spawning has a single source of truth for the
    count.
    """
    out: dict[str, int] = {}
    for lens in cfg.lenses:
        if isinstance(lens.cameras, list):
            out[lens.name] = lens.cameras[run_index]
        else:
            out[lens.name] = lens.cameras
    return out


def _lens_copies_for_run(cfg: BenchmarkConfig, run_index: int) -> dict[str, int]:
    """Resolve every lens's copy count for this run.

    Same shape as `_lens_cameras_for_run`: scalar `copies` stays
    constant across runs; list `copies` picks element `run_index`. The
    harness pre-provisions `max(lens.copies)` detectors per stage at
    startup but only activates the first `out[lens.name]` copies per
    run.
    """
    out: dict[str, int] = {}
    for lens in cfg.lenses:
        if isinstance(lens.copies, list):
            out[lens.name] = lens.copies[run_index]
        else:
            out[lens.name] = lens.copies
    return out


def _build_worker_args(
    lens,
    sds: list[StageDetector],
    objects: int | None,
    cfg: BenchmarkConfig,
    edge_url: str,
    log_file: str,
    duration_seconds: float,
    worker_number: int,
    camera: int,
    copy_index: int,
):
    """Build the (target_fn, kwargs) pair for one camera process.

    Resolves per-lens overrides (image_size, target_fps) against globals
    and picks the right runner function plus the right detector IDs
    from `sds` (the stage detectors for THIS (lens, copy_index) pair —
    caller filters before passing).

    Args:
        lens: A LensSpec subtype (SingleBinaryLens, SingleBboxLens, or
            BboxToBinaryLens).
        sds: Stage detectors for the (lens, copy) pair this worker
            serves (typically 1 or 2 entries — one per stage).
        objects: This run's `objects` value for the lens, or None if the
            lens has no `objects` (single_binary case).
        cfg: Full benchmark config — used to resolve global defaults.
        edge_url: Edge endpoint URL the worker should hit.
        log_file: JSONL log path the worker should append to.
        duration_seconds: Total worker lifetime including warmup.
        worker_number: Global worker index (across all lenses + cameras + copies).
        camera: Per-(lens, copy) camera index.
        copy_index: Which copy of the lens this worker serves; passed
            through to lens runners so events are tagged with `copy`.

    Returns:
        (target_fn, kwargs_dict) suitable for multiprocessing.Process.
    """
    image_size = tuple(lens.image_size if lens.image_size is not None else cfg.globals_.image_size)
    target_fps = lens.target_fps if lens.target_fps is not None else cfg.globals_.target_fps
    common = dict(
        worker_number=worker_number, camera=camera, lens_name=lens.name,
        copy_index=copy_index,
        edge_url=edge_url, image_size=image_size, target_fps=target_fps,
        duration_seconds=duration_seconds, log_file=log_file,
    )
    if isinstance(lens, SingleBinaryLens):
        single = next(sd for sd in sds if sd.stage == "single")
        return lenses.run_single_binary, {**common, "detector_id": single.detector_id}
    if isinstance(lens, SingleBboxLens):
        single = next(sd for sd in sds if sd.stage == "single")
        return lenses.run_single_bbox, {**common, "detector_id": single.detector_id, "objects": objects}
    if isinstance(lens, BboxToBinaryLens):
        bbox = next(sd for sd in sds if sd.stage == "bbox")
        binary = next(sd for sd in sds if sd.stage == "binary")
        return lenses.run_bbox_to_binary, {
            **common,
            "bbox_detector_id": bbox.detector_id,
            "binary_detector_id": binary.detector_id,
            "objects": objects,
        }
    raise RuntimeError(f"unknown lens type: {type(lens).__name__}")


def _spawn_lens_workers(
    cfg: BenchmarkConfig,
    run: ResolvedRun,
    edge_url: str,
    run_dir: Path,
    duration_seconds: float,
) -> list[mp.Process]:
    """Start one Process per (lens × copy × camera) and return them.

    Workers are started in lens-config order, then copy, then camera;
    worker_number increments monotonically. Each worker writes to its
    own log file in `run_dir` — no shared writer, so no inter-process
    race on the log. Log filenames omit the copy suffix when the lens
    has only one copy (back-compat with pre-copies layouts) and include
    `_copy{k}` when multiple copies are active.

    Args:
        cfg: Benchmark config (for lens list and overrides).
        run: ResolvedRun providing lens_objects, lens_cameras,
            lens_copies, and the shared stage_detectors.
        edge_url: Edge endpoint URL passed into each worker.
        run_dir: Per-run output directory; per-camera log files live here.
        duration_seconds: How long each worker should run before exiting.

    Returns:
        List of started Process objects (already `.start()`ed).
    """
    # Group stage_detectors by (lens_name, copy_index) so worker spawn
    # can hand each worker the correct subset for its (lens, copy) pair.
    by_lens_copy: dict[tuple[str, int], list[StageDetector]] = {}
    for sd in run.stage_detectors:
        by_lens_copy.setdefault((sd.lens_name, sd.copy_index), []).append(sd)
    procs: list[mp.Process] = []
    worker_number = 0
    for lens in cfg.lenses:
        cameras_this_run = run.lens_cameras[lens.name]
        copies_this_run = run.lens_copies[lens.name]
        for copy_idx in range(copies_this_run):
            sds = by_lens_copy[(lens.name, copy_idx)]
            for cam_idx in range(cameras_this_run):
                log_path = run_dir / _camera_log_name(lens.name, copy_idx, cam_idx, copies_this_run)
                target, kwargs = _build_worker_args(
                    lens, sds, run.lens_objects.get(lens.name), cfg, edge_url,
                    str(log_path), duration_seconds, worker_number, cam_idx,
                    copy_index=copy_idx,
                )
                proc_name = f"{lens.name}_copy{copy_idx}_cam{cam_idx}" if copies_this_run > 1 else f"{lens.name}_cam{cam_idx}"
                p = mp.Process(target=target, kwargs=kwargs, name=proc_name)
                p.start()
                procs.append(p)
                worker_number += 1
    return procs


def _camera_log_name(lens_name: str, copy_idx: int, cam_idx: int, copies_in_run: int) -> str:
    """JSONL log filename for one worker process.

    With copies > 1, the filename includes `_copy{k}` so each copy's
    workers write to distinct files. When copies == 1, the legacy
    `camera_{lens}_{N}.log` shape is preserved — important for re-runs
    that compare against existing baseline benchmarks.
    """
    if copies_in_run > 1:
        return f"camera_{lens_name}_copy{copy_idx}_{cam_idx}.log"
    return f"camera_{lens_name}_{cam_idx}.log"


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
        "lens_objects": run.lens_objects,
        "lens_cameras": run.lens_cameras,
        "lens_copies": run.lens_copies,
        "lenses": [
            {
                "name": l.name,
                "type": l.type,
                # Per-run camera / copy counts, not the raw config fields
                # — so the report's per-run table iterates over exactly
                # the (copy, camera) pairs that ran in this iteration
                # (relevant when `cameras` or `copies` ramps).
                "cameras": run.lens_cameras[l.name],
                "copies": run.lens_copies[l.name],
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
        # Cloud provisioning is one-shot (all detectors + copies created
        # and trained upfront — parallel training stays). The EDGE config,
        # however, ramps per-run: each run loads only the detectors it
        # exercises, so the loaded count (and its VRAM/compute footprint)
        # tracks the copies ramp instead of staying pinned at max(copies).
        logger.info("provisioning detectors (one-shot cloud create+train, reused across all runs)")
        stage_detectors = dm.provision_all()
        prev_active_ids: frozenset[str] | None = None
        for i in range(n_runs):
            lens_objects = _lens_objects_for_run(cfg, i)
            lens_cameras = _lens_cameras_for_run(cfg, i)
            lens_copies = _lens_copies_for_run(cfg, i)
            logger.info(
                "[run %d/%d] lens_objects=%s lens_cameras=%s lens_copies=%s",
                i + 1, n_runs, lens_objects, lens_cameras, lens_copies,
            )
            run = ResolvedRun(
                run_index=i,
                lens_objects=lens_objects,
                lens_cameras=lens_cameras,
                lens_copies=lens_copies,
                stage_detectors=stage_detectors,
            )
            # Push only this run's active detectors, and only when the
            # set changes. With no copies ramp the set is constant, so
            # this pushes once at run 0 and never again — identical to
            # the old single-push behavior. The edge reconciles
            # incrementally, so a ramp only cold-starts the new copies.
            active = dm.active_detectors_for_run(stage_detectors, lens_copies)
            active_ids = frozenset(sd.detector_id for sd in active)
            if active_ids != prev_active_ids:
                logger.info(
                    "[run %d/%d] edge config: loading %d detector(s) (was %s)",
                    i + 1, n_runs, len(active),
                    "none" if prev_active_ids is None else len(prev_active_ids),
                )
                try:
                    dm.push_edge_config(active)
                except Exception:
                    logger.exception(
                        "[run %d/%d] edge set_config failed loading %d detector(s) — "
                        "likely the edge hit a resource limit (e.g. VRAM) at this copy "
                        "count. Writing partial results for the %d completed run(s).",
                        i + 1, n_runs, len(active), len(summaries),
                    )
                    break
                prev_active_ids = active_ids
            summaries.append(_run_one(cfg, run, out_root))
    except KeyboardInterrupt:
        logger.warning("interrupted; running cleanup via atexit")
        return 130
    except Exception:
        logger.exception("benchmark run failed")
        if not summaries:
            return 1
        # An unexpected error after some runs completed: still write what
        # we have so the partial data isn't lost, but exit non-zero so
        # the failure is visible to callers / CI.
        logger.warning("writing partial results for %d completed run(s)", len(summaries))
        run_failed = True
    else:
        run_failed = False

    if not summaries:
        logger.error("no runs completed; nothing to report")
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
    return 1 if run_failed else 0


if __name__ == "__main__":
    sys.exit(main())
