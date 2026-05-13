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

from groundlight import Detector, ExperimentalApi
from groundlight.edge import NO_CLOUD, EdgeEndpointConfig
from pydantic import BaseModel, ConfigDict

import groundlight_helpers as glh
from app_benchmark.config import (
    BboxToBinaryLens,
    BenchmarkConfig,
    SingleBboxLens,
    SingleBinaryLens,
)

logger = logging.getLogger(__name__)

_MAX_PREFIX_LEN = 28


class StageDetector(BaseModel):
    """One provisioned cloud detector representing a single stage of a lens.

    Attributes:
        lens_name: Name of the lens this detector serves.
        stage: One of "single" (used by both single_binary and single_bbox
            lenses), "bbox", or "binary" (the two stages of a
            bbox_to_binary lens).
        detector: SDK Detector instance — used when (re)pushing the edge
            config. Not a Pydantic model, hence arbitrary_types_allowed.
        detector_id: Convenience handle (== detector.id) for the worker
            kwargs; saves an attribute lookup per request.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)
    lens_name: str
    stage: str  # "single", "bbox", or "binary"
    detector: Detector
    detector_id: str


class ResolvedRun(BaseModel):
    """Per-run binding handed to the worker spawner.

    Detectors are provisioned ONCE for the whole benchmark, so
    `stage_detectors` is identical across every run; the only thing that
    varies between runs is `lens_n`, which the workers consume to vary
    image synthesis and (for chained lenses) the downstream call count.

    Attributes:
        run_index: 0-based index into the n-list sweep.
        lens_n: Mapping from lens_name -> the `n` value for this run.
            Lenses without an `n` field are absent from the dict.
        stage_detectors: Shared list of detectors registered on the edge.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)
    run_index: int
    lens_n: dict[str, int]
    stage_detectors: list[StageDetector]


def _name_prefix(detector_name_prefix: str, run_name: str, lens_name: str, suffix: str = "") -> str:
    """Build a cloud detector name prefix.

    The SDK's provision_detector appends roughly 30 chars of suffix
    (image dims, mode, n, pipeline hash), and the Predictor name on the
    cloud side adds another ~15-20 chars. We cap the prefix at ≤28 chars
    so the full name stays under the 100-char Groundlight limit. Long
    lens names get hashed.

    Args:
        detector_name_prefix: The user-configured prefix from `run.detector_name_prefix`.
        run_name: The benchmark name (hashed to 6 hex chars, ties detectors
            from the same benchmark together).
        lens_name: The lens this detector serves.
        suffix: Optional stage qualifier ("bbox" or "binary") for chained
            lenses where one lens has two detectors.

    Returns:
        Prefix string of length ≤28 chars.
    """
    run_hash = hashlib.sha256(run_name.encode()).hexdigest()[:6]
    candidate = f"{detector_name_prefix}_{run_hash}_{lens_name}"
    if suffix:
        candidate += f"_{suffix}"
    if len(candidate) <= _MAX_PREFIX_LEN:
        return candidate
    lens_hash = hashlib.sha256(f"{lens_name}_{suffix}".encode()).hexdigest()[:8]
    return f"{detector_name_prefix}_{run_hash}_{lens_hash}"


class DetectorManager:
    """Owns the detector lifecycle for the whole benchmark.

    Responsibilities:
      - Snapshot the pre-run edge config so we can restore it at exit.
      - Provision (create + prime + wait for training) every detector
        the benchmark needs, once, before any run starts.
      - Push a single edge config containing all detectors in NO_CLOUD
        mode.
      - Restore the snapshotted edge config and best-effort delete every
        cloud detector at exit (via atexit in cli.py).
    """

    def __init__(
        self,
        cfg: BenchmarkConfig,
        gl_cloud: ExperimentalApi,
        gl_edge: ExperimentalApi,
    ) -> None:
        """Wire up the manager with a validated config and two SDK clients.

        Args:
            cfg: The benchmark config.
            gl_cloud: SDK client pointed at the Groundlight cloud (used
                for detector CRUD and pipeline training).
            gl_edge: SDK client pointed at the local edge endpoint (used
                for edge.get_config / set_config).
        """
        self.cfg = cfg
        self.gl_cloud = gl_cloud
        self.gl_edge = gl_edge
        self._pre_run_edge_config: EdgeEndpointConfig | None = None
        self._all_created: dict[str, Detector] = {}

    def snapshot_edge_config(self) -> None:
        """Capture the current edge config so restore_edge_config() can
        put it back at cleanup. Failures are downgraded to a warning and
        an empty config snapshot — we still try to clean up our own
        detectors at exit either way.
        """
        try:
            self._pre_run_edge_config = self.gl_edge.edge.get_config()
        except Exception as exc:
            logger.warning("could not snapshot pre-run edge config: %s", exc)
            self._pre_run_edge_config = EdgeEndpointConfig()

    def restore_edge_config(self) -> bool:
        """Push the pre-run edge config back. Returns True on success;
        False if no snapshot was taken or the push failed (the error is
        logged but never re-raised — this runs from atexit)."""
        if self._pre_run_edge_config is None:
            return False
        try:
            self.gl_edge.edge.set_config(self._pre_run_edge_config)
            return True
        except Exception as exc:
            logger.error("failed to restore pre-run edge config: %s", exc)
            return False

    def provision_all(self) -> list[StageDetector]:
        """Create + train (if needed) every detector the benchmark uses.

        Called exactly once before the run loop. Each lens stage maps to
        one detector:
            single_binary:     1 BINARY detector
            single_bbox:       1 BOUNDING_BOX detector with max_num_bboxes = max(lens.n)
            bbox_to_binary:    1 BOUNDING_BOX (upstream) + 1 BINARY (downstream)
        Detectors are named deterministically from the run name + lens
        name + stage suffix, so re-running the same config reuses the
        existing detectors (no retraining).

        Returns:
            The flat list of StageDetector objects for the whole
            benchmark. Stored on `self._all_stage_detectors` for
            push_edge_config and delete_all to use, and returned for the
            caller to hand to the worker spawner.
        """
        run_name = self.cfg.run.name
        name_prefix = self.cfg.run.detector_name_prefix
        stage_detectors: list[StageDetector] = []

        for lens in self.cfg.lenses:
            image_size = lens.image_size if lens.image_size is not None else self.cfg.globals_.image_size
            max_n = max(lens.n) if hasattr(lens, "n") else None
            if isinstance(lens, SingleBinaryLens):
                det = self._provision(
                    prefix=_name_prefix(name_prefix, run_name, lens.name),
                    mode="BINARY", image_size=image_size,
                    pipeline=lens.pipeline, n=None,
                )
                stage_detectors.append(StageDetector(
                    lens_name=lens.name, stage="single", detector=det, detector_id=det.id))
            elif isinstance(lens, SingleBboxLens):
                assert max_n is not None
                det = self._provision(
                    prefix=_name_prefix(name_prefix, run_name, lens.name),
                    mode="BOUNDING_BOX", image_size=image_size,
                    pipeline=lens.pipeline, n=max_n,
                )
                stage_detectors.append(StageDetector(
                    lens_name=lens.name, stage="single", detector=det, detector_id=det.id))
            elif isinstance(lens, BboxToBinaryLens):
                assert max_n is not None
                bbox_det = self._provision(
                    prefix=_name_prefix(name_prefix, run_name, lens.name, "bbox"),
                    mode="BOUNDING_BOX", image_size=image_size,
                    pipeline=lens.bbox_pipeline, n=max_n,
                )
                bin_det = self._provision(
                    prefix=_name_prefix(name_prefix, run_name, lens.name, "binary"),
                    mode="BINARY", image_size=image_size,
                    pipeline=lens.binary_pipeline, n=None,
                )
                stage_detectors.append(StageDetector(
                    lens_name=lens.name, stage="bbox", detector=bbox_det, detector_id=bbox_det.id))
                stage_detectors.append(StageDetector(
                    lens_name=lens.name, stage="binary", detector=bin_det, detector_id=bin_det.id))
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
        """Thin wrapper over groundlight_helpers.provision_detector that
        tracks every created detector in `_all_created` for delete_all().

        Args:
            prefix: Detector name prefix from `_name_prefix(...)`.
            mode: One of "BINARY", "BOUNDING_BOX", "COUNT", "MULTI_CLASS".
            image_size: (width, height) used for the priming images.
            pipeline: Optional pipeline config name; None uses the cloud
                default for the mode.
            n: Mode-specific knob (max_num_bboxes for BOUNDING_BOX,
                max_count for COUNT, etc.); None for BINARY.

        Returns:
            The SDK Detector object (created or existing).
        """
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
        """Push a single edge config containing every benchmark detector
        in NO_CLOUD mode. Called once before the run loop.

        Merges with the snapshotted pre-run edge config (if any) so that
        detectors that were already loaded on the edge survive the
        benchmark — they'll be restored cleanly at cleanup. This blocks
        until inference pods report ready (or `set_config_timeout_seconds`
        elapses).

        Args:
            stage_detectors: Result of provision_all().
        """
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
        """Best-effort delete every detector we provisioned across all runs.

        Returns:
            (deleted_count, failed_count). Never raises — runs from
            atexit and we don't want to mask any prior exception.
        """
        deleted = failed = 0
        for det in self._all_created.values():
            try:
                self.gl_cloud.delete_detector(det.id)
                deleted += 1
            except Exception as exc:
                failed += 1
                logger.error("failed to delete %s: %s", det.id, exc)
        return deleted, failed
