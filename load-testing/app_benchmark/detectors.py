"""Detector lifecycle: cloud provision (with training) + per-run edge config push.

Reuses load-testing/groundlight_helpers.provision_detector — every detector is
named deterministically by (run_name, lens_name, stage, n) so unchanged
detectors are cached across runs and don't re-prime.
"""

import hashlib
import logging
from dataclasses import dataclass

from groundlight import Detector, ExperimentalApi
from groundlight.edge import NO_CLOUD, EdgeEndpointConfig

import groundlight_helpers as glh
from app_benchmark.config import (
    BboxToBinaryLens,
    BenchmarkConfig,
    SingleBboxLens,
    SingleBinaryLens,
)

logger = logging.getLogger(__name__)

_MAX_PREFIX_LEN = 28


@dataclass(frozen=True)
class StageDetector:
    """One provisioned cloud detector for one stage of one lens in one run."""
    lens_name: str
    stage: str  # "single", "bbox", or "binary"
    detector: Detector
    detector_id: str


@dataclass
class ResolvedRun:
    run_index: int
    lens_n: dict[str, int]
    stage_detectors: list[StageDetector]


def _name_prefix(run_name: str, lens_name: str, suffix: str = "") -> str:
    """Cloud detector name prefix; ≤28 chars to leave room for the
    image/mode/n suffix that provision_detector appends internally."""
    run_hash = hashlib.sha256(run_name.encode()).hexdigest()[:6]
    candidate = f"bench_{run_hash}_{lens_name}"
    if suffix:
        candidate += f"_{suffix}"
    if len(candidate) <= _MAX_PREFIX_LEN:
        return candidate
    lens_hash = hashlib.sha256(f"{lens_name}_{suffix}".encode()).hexdigest()[:8]
    return f"bench_{run_hash}_{lens_hash}"


class DetectorManager:
    def __init__(
        self,
        cfg: BenchmarkConfig,
        gl_cloud: ExperimentalApi,
        gl_edge: ExperimentalApi,
    ) -> None:
        self.cfg = cfg
        self.gl_cloud = gl_cloud
        self.gl_edge = gl_edge
        self._pre_run_edge_config: EdgeEndpointConfig | None = None
        self._all_created: dict[str, Detector] = {}

    def snapshot_edge_config(self) -> None:
        try:
            self._pre_run_edge_config = self.gl_edge.edge.get_config()
        except Exception as exc:
            logger.warning("could not snapshot pre-run edge config: %s", exc)
            self._pre_run_edge_config = EdgeEndpointConfig()

    def restore_edge_config(self) -> bool:
        if self._pre_run_edge_config is None:
            return False
        try:
            self.gl_edge.edge.set_config(self._pre_run_edge_config)
            return True
        except Exception as exc:
            logger.error("failed to restore pre-run edge config: %s", exc)
            return False

    def provision_run(self, run_index: int, lens_n: dict[str, int]) -> ResolvedRun:
        """Cloud-create / train (if needed) every detector this run uses.
        Cached by deterministic name across runs."""
        run_name = self.cfg.run.name
        stage_detectors: list[StageDetector] = []

        for lens in self.cfg.lenses:
            n = lens_n.get(lens.name)
            image_size = lens.image_size if lens.image_size is not None else self.cfg.globals_.image_size
            if isinstance(lens, SingleBinaryLens):
                det = self._provision(
                    prefix=_name_prefix(run_name, lens.name),
                    mode="BINARY", image_size=image_size,
                    pipeline=lens.pipeline, n=None,
                )
                stage_detectors.append(StageDetector(lens.name, "single", det, det.id))
            elif isinstance(lens, SingleBboxLens):
                assert n is not None
                det = self._provision(
                    prefix=_name_prefix(run_name, lens.name),
                    mode="BOUNDING_BOX", image_size=image_size,
                    pipeline=lens.pipeline, n=n,
                )
                stage_detectors.append(StageDetector(lens.name, "single", det, det.id))
            elif isinstance(lens, BboxToBinaryLens):
                assert n is not None
                bbox_det = self._provision(
                    prefix=_name_prefix(run_name, lens.name, "bbox"),
                    mode="BOUNDING_BOX", image_size=image_size,
                    pipeline=lens.bbox_pipeline, n=n,
                )
                bin_det = self._provision(
                    prefix=_name_prefix(run_name, lens.name, "binary"),
                    mode="BINARY", image_size=image_size,
                    pipeline=lens.binary_pipeline, n=None,
                )
                stage_detectors.append(StageDetector(lens.name, "bbox", bbox_det, bbox_det.id))
                stage_detectors.append(StageDetector(lens.name, "binary", bin_det, bin_det.id))
            else:
                raise RuntimeError(f"unknown lens type: {type(lens).__name__}")

        return ResolvedRun(run_index=run_index, lens_n=lens_n, stage_detectors=stage_detectors)

    def _provision(
        self,
        *,
        prefix: str,
        mode: str,
        image_size: tuple[int, int],
        pipeline: str | None,
        n: int | None,
    ) -> Detector:
        det = glh.provision_detector(
            self.gl_cloud,
            detector_mode=mode,
            detector_name_prefix=prefix,
            image_width=image_size[0],
            image_height=image_size[1],
            edge_pipeline_config=pipeline,
            n=n,
        )
        self._all_created[det.name] = det
        return det

    def push_edge_config(self, run: ResolvedRun) -> None:
        """Push edge config with this run's detectors in NO_CLOUD mode.
        Includes the pre-run snapshot so any detectors that were already
        configured continue to live alongside ours."""
        if self._pre_run_edge_config is not None:
            edge_config = self._pre_run_edge_config.model_copy(deep=True)
        else:
            edge_config = EdgeEndpointConfig()
        for sd in run.stage_detectors:
            edge_config.add_detector(sd.detector, NO_CLOUD)
        self.gl_edge.edge.set_config(
            edge_config, timeout_sec=self.cfg.run.set_config_timeout_seconds,
        )

    def delete_all(self) -> tuple[int, int]:
        """Best-effort delete every detector we provisioned across all runs."""
        deleted = failed = 0
        for det in self._all_created.values():
            try:
                self.gl_cloud.delete_detector(det.id)
                deleted += 1
            except Exception as exc:
                failed += 1
                logger.error("failed to delete %s: %s", det.id, exc)
        return deleted, failed
