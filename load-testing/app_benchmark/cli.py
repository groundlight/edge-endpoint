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
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path(template.format(name=run_name, ts=ts))


def _lens_n_for_run(cfg: BenchmarkConfig, run_index: int) -> dict[str, int]:
    out: dict[str, int] = {}
    for lens in cfg.lenses:
        if hasattr(lens, "n"):
            out[lens.name] = lens.n[run_index]
    return out


def _worker_for(
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
    log_file: str,
    duration_seconds: float,
) -> list[mp.Process]:
    by_lens: dict[str, list[StageDetector]] = {}
    for sd in run.stage_detectors:
        by_lens.setdefault(sd.lens_name, []).append(sd)
    procs: list[mp.Process] = []
    worker_number = 0
    for lens in cfg.lenses:
        sds = by_lens[lens.name]
        for cam_idx in range(lens.cameras):
            target, kwargs = _worker_for(
                lens, sds, run.lens_n.get(lens.name), cfg, edge_url,
                log_file, duration_seconds, worker_number, cam_idx,
            )
            p = mp.Process(target=target, kwargs=kwargs, name=f"{lens.name}_cam{cam_idx}")
            p.start()
            procs.append(p)
            worker_number += 1
    return procs


def _emit_ramp_marker(log_file: Path, total_clients: int) -> None:
    """Single fake RAMP marker so parse_load_test_logs can compute clients_by_second."""
    with log_file.open("a", encoding="utf-8") as f:
        f.write(f"RAMP {total_clients} ts={time.time()}\n")


def _join_with_grace(procs: list[mp.Process], timeout_s: float) -> None:
    deadline = time.time() + timeout_s
    for p in procs:
        remaining = max(0.0, deadline - time.time())
        p.join(remaining)
    for p in procs:
        if p.is_alive():
            logger.warning("worker %s still alive after timeout; terminating", p.name)
            p.terminate()
            p.join(5)


def _run_one(
    cfg: BenchmarkConfig,
    run: ResolvedRun,
    out_root: Path,
) -> dict:
    run_dir = out_root / f"run_{run.run_index:02d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    log_file = run_dir / "load_test.log"
    log_file.touch()

    duration = float(cfg.globals_.duration_seconds)
    warmup = float(cfg.globals_.warmup_seconds)
    total_cameras = sum(l.cameras for l in cfg.lenses)

    monitor = SystemMonitor(
        str(log_file),
        sample_interval=1.0 / cfg.monitoring.sample_hz,
        endpoint=cfg.run.edge_endpoint_url,
    )
    monitor.start()

    try:
        # Workers run for warmup + duration. Main thread sleeps `warmup`,
        # then drops a ramp marker that becomes the post-warmup t0 for the report.
        worker_lifetime = warmup + duration
        procs = _spawn_lens_workers(
            cfg, run, cfg.run.edge_endpoint_url, str(log_file), worker_lifetime,
        )
        logger.info("[run %d] %d worker(s) spawned; warmup %.0fs, main %.0fs",
                    run.run_index, len(procs), warmup, duration)
        if warmup > 0:
            time.sleep(warmup)
        main_start_ts = time.time()
        _emit_ramp_marker(log_file, total_cameras)
        time.sleep(duration)
        _join_with_grace(procs, timeout_s=30.0)
        main_end_ts = time.time()
    finally:
        monitor.stop()

    run_meta = {
        "run_index": run.run_index,
        "lens_n": run.lens_n,
        "lenses": [
            {
                "name": l.name,
                "type": l.type,
                "cameras": l.cameras,
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
    }
    return report.write_run_artifacts(run_dir, log_file, run_meta, main_start_ts)


def main(argv: list[str] | None = None) -> int:
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
            logger.info("[run %d/%d] lens_n=%s", i + 1, n_runs, lens_n)
            run = ResolvedRun(run_index=i, lens_n=lens_n, stage_detectors=stage_detectors)
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
