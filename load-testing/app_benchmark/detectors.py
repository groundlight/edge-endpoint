"""Detector lifecycle: one-shot cloud provision (with training) + one-shot
edge config push.

For n-bearing lenses, the bbox detector is created once with
`max_num_bboxes = max(lens.n)` — the upper bound. The model's inference
cost is essentially independent of `max_num_bboxes` (it processes the
whole image regardless; only NMS post-processing depends on actual
detected count, which is negligible). The per-run `n` variation lives
entirely in the worker: image synthesis bounds + number of downstream
binary calls in `bbox_to_binary`.
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
    """Per-run binding: which `n` each lens uses, plus the (shared, static)
    list of stage detectors. Detectors are provisioned once for the whole
    benchmark — this just records which `n` the workers should run with."""
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

    def provision_all(self) -> list[StageDetector]:
        """Cloud-create / train (if needed) every detector the benchmark uses,
        ONCE. For n-bearing lenses, uses max(lens.n) for max_num_bboxes."""
        run_name = self.cfg.run.name
        stage_detectors: list[StageDetector] = []

        for lens in self.cfg.lenses:
            image_size = lens.image_size if lens.image_size is not None else self.cfg.globals_.image_size
            max_n = max(lens.n) if hasattr(lens, "n") else None
            if isinstance(lens, SingleBinaryLens):
                det = self._provision(
                    prefix=_name_prefix(run_name, lens.name),
                    mode="BINARY", image_size=image_size,
                    pipeline=lens.pipeline, n=None,
                )
                stage_detectors.append(StageDetector(lens.name, "single", det, det.id))
            elif isinstance(lens, SingleBboxLens):
                assert max_n is not None
                det = self._provision(
                    prefix=_name_prefix(run_name, lens.name),
                    mode="BOUNDING_BOX", image_size=image_size,
                    pipeline=lens.pipeline, n=max_n,
                )
                stage_detectors.append(StageDetector(lens.name, "single", det, det.id))
            elif isinstance(lens, BboxToBinaryLens):
                assert max_n is not None
                bbox_det = self._provision(
                    prefix=_name_prefix(run_name, lens.name, "bbox"),
                    mode="BOUNDING_BOX", image_size=image_size,
                    pipeline=lens.bbox_pipeline, n=max_n,
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
        self._all_stage_detectors = stage_detectors
        return stage_detectors

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

    def push_edge_config(self, stage_detectors: list[StageDetector]) -> None:
        """Push edge config with all benchmark detectors in NO_CLOUD mode.
        Called once before the run loop — the same detectors serve every run.
        Includes the pre-run snapshot so any detectors that were already
        configured continue to live alongside ours."""
        if self._pre_run_edge_config is not None:
            edge_config = self._pre_run_edge_config.model_copy(deep=True)
        else:
            edge_config = EdgeEndpointConfig()
        for sd in stage_detectors:
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
