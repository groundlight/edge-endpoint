"""Spawns/joins client processes (one per lens × camera) plus the monitor."""

import logging
import multiprocessing as mp
import time
from typing import Any

from app_benchmark.client import run_client
from app_benchmark.config import BenchmarkConfig
from app_benchmark.detectors import CreatedDetector

logger = logging.getLogger(__name__)


class Supervisor:
    def __init__(
        self,
        cfg: BenchmarkConfig,
        created: list[CreatedDetector],
        monitor_target,
        monitor_args: tuple[Any, ...],
    ) -> None:
        self.cfg = cfg
        self.created = created
        self.ctx = mp.get_context("spawn")
        self.stop_event = self.ctx.Event()
        # Queue maxsize is bounded by the OS POSIX semaphore SEM_VALUE_MAX. On
        # macOS that limit is 32767; Linux is much higher but we cap uniformly.
        # At 60 fps × ~10 stage events × Σcameras the queue fills slowly
        # because metrics_writer drains continuously; 32k is plenty of headroom.
        self.frame_queue: mp.Queue = self.ctx.Queue(maxsize=32_000)
        self.sample_queue: mp.Queue = self.ctx.Queue(maxsize=4_000)
        self._monitor_target = monitor_target
        self._monitor_args = monitor_args
        self._processes: list[mp.Process] = []
        self._client_count = 0

    def detector_id_by_name(self) -> dict[str, str]:
        return {c.spec_name: c.detector_id for c in self.created}

    def start(self) -> None:
        det_map = self.detector_id_by_name()
        edge_url = self.cfg.run.edge_endpoint_url

        monitor = self.ctx.Process(
            target=self._monitor_target,
            args=(self.cfg.monitoring.sample_hz, self.sample_queue, self.frame_queue,
                  self.stop_event, edge_url, *self._monitor_args),
            name="monitor",
        )
        monitor.start()
        self._processes.append(monitor)

        for lens in self.cfg.lenses:
            for cam_idx in range(lens.cameras):
                client_id = f"{lens.name}_cam{cam_idx}"
                p = self.ctx.Process(
                    target=run_client,
                    args=(client_id, cam_idx, lens, det_map, edge_url,
                          self.frame_queue, self.stop_event),
                    name=client_id,
                )
                p.start()
                self._processes.append(p)
                self._client_count += 1
        logger.info("supervisor started %d client(s) + 1 monitor",
                    self._client_count, extra={"phase": "run"})

    def wait(self, duration_s: float) -> None:
        deadline = time.time() + duration_s
        while time.time() < deadline:
            if self.stop_event.is_set():
                return
            time.sleep(0.5)

    def signal_stop(self) -> None:
        self.stop_event.set()

    def stop(self, grace_s: float = 10.0) -> None:
        self.stop_event.set()
        deadline = time.time() + grace_s
        for p in self._processes:
            remaining = max(0.0, deadline - time.time())
            p.join(timeout=remaining)
        for p in self._processes:
            if p.is_alive():
                logger.warning("force-terminating %s (did not exit within grace)", p.name,
                               extra={"phase": "shutdown"})
                p.terminate()
                p.join(timeout=2.0)

    def alive_clients(self) -> int:
        # Index 0 is the monitor; clients are indices 1..N.
        return sum(1 for p in self._processes[1:] if p.is_alive())

    @property
    def total_clients(self) -> int:
        return self._client_count
