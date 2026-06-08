"""Detector lifecycle: one-shot cloud provision (with training) + one-shot
edge config push.

For lenses that declare `objects` as a list, the bbox detector is
created once with `max_num_bboxes = max(lens.objects)` — the upper
bound. The model's inference cost is essentially independent of
`max_num_bboxes` (it processes the whole image regardless; only NMS
post-processing depends on actual detected count, which is negligible).
The per-run `objects` variation lives entirely in the worker: image
synthesis bounds + number of downstream binary calls in `bbox_to_binary`.
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
from app_benchmark.constants import BINARY_DOWNSTREAM_SIZE

logger = logging.getLogger(__name__)

_MAX_PREFIX_LEN = 28


class StageDetector(BaseModel):
    """One provisioned cloud detector representing a single stage of a lens.

    Attributes:
        lens_name: Name of the lens this detector serves.
        stage: One of "single" (used by both single_binary and single_bbox
            lenses), "bbox", or "binary" (the two stages of a
            bbox_to_binary lens).
        copy_index: Which copy of the lens this detector backs.
            Zero-based; lenses with no copies-ramp always use copy 0.
            Each copy is an independently-trained detector with the
            same pipeline as its siblings — useful for measuring the
            server's capacity to juggle multiple distinct detectors.
        detector: SDK Detector instance — used when (re)pushing the edge
            config. Not a Pydantic model, hence arbitrary_types_allowed.
        detector_id: Convenience handle (== detector.id) for the worker
            kwargs; saves an attribute lookup per request.
        is_external: True when the detector was supplied by the user via
            `*_detector_id` in the config. External detectors skip
            creation + training at startup and skip cloud deletion at
            cleanup; everything else (edge config push, NO_CLOUD
            inference) is identical. External + copies > 1 is rejected
            by the schema validator.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)
    lens_name: str
    stage: str  # "single", "bbox", or "binary"
    copy_index: int = 0
    detector: Detector
    detector_id: str
    is_external: bool = False


class ResolvedRun(BaseModel):
    """Per-run binding handed to the worker spawner.

    Detectors are provisioned ONCE for the whole benchmark, so
    `stage_detectors` is identical across every run. What varies between
    runs are the per-lens sweep values: `lens_objects` controls image
    synthesis and chained-call counts; `lens_cameras` controls how many
    worker processes to spawn per (lens, copy); `lens_copies` controls
    how many distinct detector copies of the lens are active.

    Attributes:
        run_index: 0-based index into the sweep.
        lens_objects: Mapping from lens_name -> the `objects` value for
            this run (objects placed per synthetic frame, and downstream
            binary-call count for chained lenses). Lenses without an
            `objects` field are absent from the dict.
        lens_cameras: Mapping from lens_name -> the camera count for
            this run. Every lens is present (scalar `cameras` resolves
            to the same value across every run).
        lens_copies: Mapping from lens_name -> the copy count for this
            run. Every lens is present (scalar `copies` resolves to the
            same value across every run). Workers spawn for copies 0
            through `lens_copies[lens] - 1`; the harness pre-provisions
            `max(lens.copies)` detectors per stage but only activates
            the first `lens_copies[lens]` of them in any given run.
        stage_detectors: Shared list of detectors registered on the edge
            (max(copies) per stage per lens).
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)
    run_index: int
    lens_objects: dict[str, int]
    lens_cameras: dict[str, int]
    lens_copies: dict[str, int]
    stage_detectors: list[StageDetector]


def _name_prefix(
    detector_name_prefix: str,
    run_name: str,
    lens_name: str,
    suffix: str = "",
    copy_index: int = 0,
) -> str:
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
        copy_index: Index into the copies-ramp; zero means "the default
            copy" and is omitted from the prefix to keep names compact
            for the common case. Non-zero copies append `_copy{k}` so
            every copy gets a deterministic, unique cloud-side name.

    Returns:
        Prefix string of length ≤28 chars.
    """
    run_hash = hashlib.sha256(run_name.encode()).hexdigest()[:6]
    candidate = f"{detector_name_prefix}_{run_hash}_{lens_name}"
    if suffix:
        candidate += f"_{suffix}"
    if copy_index:
        candidate += f"_copy{copy_index}"
    if len(candidate) <= _MAX_PREFIX_LEN:
        return candidate
    # Hash-fold the long parts so the final name still fits. Include
    # copy_index in the hash key so each copy gets a unique hash.
    lens_hash = hashlib.sha256(
        f"{lens_name}_{suffix}_copy{copy_index}".encode()
    ).hexdigest()[:8]
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

        Called exactly once before the run loop. Each lens stage × copy
        maps to one detector:
            single_binary:     `max(copies)` BINARY detectors
            single_bbox:       `max(copies)` BOUNDING_BOX detectors with
                               max_num_bboxes = max(lens.objects)
            bbox_to_binary:    `max(copies)` × (BOUNDING_BOX + BINARY)
        Detector names are deterministic — `{prefix}_{run_hash}_{lens}`
        with a `_copy{k}` suffix when copy_index > 0 — so re-running the
        same config reuses the existing detectors (no retraining). Copy
        0 keeps the unsuffixed name for back-compat with v1 detectors.

        When a lens declares `*_detector_id` in the config, that stage
        uses the pre-existing detector instead of creating one — its
        pipeline is verified against the configured `*_pipeline` and
        creation + training are skipped. External detectors are also
        skipped during cleanup (see delete_all). The schema validator
        forbids combining `*_detector_id` with `copies > 1`, so the
        external branch only ever fires at copy_index 0 of a lens whose
        max_copies is 1.

        Provisioning runs in two phases (mirroring
        `groundlight_helpers.provision_detectors` but with per-lens
        prefixes):
          1. Serially create + prime every owned detector with
             `wait_for_training=False`. The slow part — server-side
             edge-pipeline training — kicks off but doesn't block.
          2. Serially wait for each owned detector's edge pipeline to
             finish training. Because training happens on the cloud
             after step 1's priming, all detectors are training in
             parallel during these waits — so total wall-clock is
             dominated by the slowest single detector, not the sum.

        External (`*_detector_id`) detectors skip both phases.

        Returns:
            The flat list of StageDetector objects for the whole
            benchmark, ordered by lens then copy. Stored on
            `self._all_stage_detectors` for push_edge_config and
            delete_all to use, and returned for the caller to hand to
            the worker spawner.
        """
        run_name = self.cfg.run.name
        name_prefix = self.cfg.run.detector_name_prefix
        stage_detectors: list[StageDetector] = []

        # Phase 1: create + prime, skip the training wait so the next
        # detector can start priming while this one is training.
        for lens in self.cfg.lenses:
            image_size = lens.image_size if lens.image_size is not None else self.cfg.globals_.image_size
            # Bbox detectors need max_num_bboxes set at creation time;
            # use the upper bound of the sweep so the same detector
            # serves every run.
            if hasattr(lens, "objects"):
                objects_values = (
                    lens.objects if isinstance(lens.objects, list) else [lens.objects]
                )
                max_objects = max(objects_values)
            else:
                max_objects = None
            max_copies = lens._max_copies()
            for copy_idx in range(max_copies):
                if isinstance(lens, SingleBinaryLens):
                    if copy_idx == 0 and lens.binary_detector_id is not None:
                        # External path only valid when max_copies == 1
                        # (validator enforces this). Goes through copy 0.
                        stage_detectors.append(self._fetch_external(
                            lens.name, "single", copy_index=copy_idx,
                            detector_id=lens.binary_detector_id,
                            expected_pipeline=lens.pipeline,
                        ))
                    else:
                        det = self._provision(
                            prefix=_name_prefix(name_prefix, run_name, lens.name, copy_index=copy_idx),
                            mode="BINARY", image_size=image_size,
                            pipeline=lens.pipeline, n=None,
                            wait_for_training=False,
                        )
                        stage_detectors.append(StageDetector(
                            lens_name=lens.name, stage="single", copy_index=copy_idx,
                            detector=det, detector_id=det.id,
                        ))
                elif isinstance(lens, SingleBboxLens):
                    assert max_objects is not None
                    if copy_idx == 0 and lens.bbox_detector_id is not None:
                        stage_detectors.append(self._fetch_external(
                            lens.name, "single", copy_index=copy_idx,
                            detector_id=lens.bbox_detector_id,
                            expected_pipeline=lens.pipeline,
                        ))
                    else:
                        det = self._provision(
                            prefix=_name_prefix(name_prefix, run_name, lens.name, copy_index=copy_idx),
                            mode="BOUNDING_BOX", image_size=image_size,
                            pipeline=lens.pipeline, n=max_objects,
                            wait_for_training=False,
                        )
                        stage_detectors.append(StageDetector(
                            lens_name=lens.name, stage="single", copy_index=copy_idx,
                            detector=det, detector_id=det.id,
                        ))
                elif isinstance(lens, BboxToBinaryLens):
                    assert max_objects is not None
                    if copy_idx == 0 and lens.bbox_detector_id is not None:
                        stage_detectors.append(self._fetch_external(
                            lens.name, "bbox", copy_index=copy_idx,
                            detector_id=lens.bbox_detector_id,
                            expected_pipeline=lens.bbox_pipeline,
                        ))
                    else:
                        bbox_det = self._provision(
                            prefix=_name_prefix(name_prefix, run_name, lens.name, "bbox", copy_index=copy_idx),
                            mode="BOUNDING_BOX", image_size=image_size,
                            pipeline=lens.bbox_pipeline, n=max_objects,
                            wait_for_training=False,
                        )
                        stage_detectors.append(StageDetector(
                            lens_name=lens.name, stage="bbox", copy_index=copy_idx,
                            detector=bbox_det, detector_id=bbox_det.id,
                        ))
                    if copy_idx == 0 and lens.binary_detector_id is not None:
                        stage_detectors.append(self._fetch_external(
                            lens.name, "binary", copy_index=copy_idx,
                            detector_id=lens.binary_detector_id,
                            expected_pipeline=lens.binary_pipeline,
                        ))
                    else:
                        bin_det = self._provision(
                            # The downstream binary stage actually serves
                            # BINARY_DOWNSTREAM_SIZE-sized images at runtime, so prime
                            # the detector with images of that same shape — priming on
                            # the upstream `image_size` (e.g. 1920x1080) trained the
                            # model on a distribution it never sees in practice.
                            prefix=_name_prefix(name_prefix, run_name, lens.name, "binary", copy_index=copy_idx),
                            mode="BINARY", image_size=BINARY_DOWNSTREAM_SIZE,
                            pipeline=lens.binary_pipeline, n=None,
                            wait_for_training=False,
                        )
                        stage_detectors.append(StageDetector(
                            lens_name=lens.name, stage="binary", copy_index=copy_idx,
                            detector=bin_det, detector_id=bin_det.id,
                        ))
                else:
                    raise RuntimeError(f"unknown lens type: {type(lens).__name__}")

        # Phase 2: wait for all owned detectors to finish training. Each
        # wait_for_edge_pipeline_trained returns immediately if the
        # pipeline is already sufficiently trained (the common case on
        # re-runs with preserve_detectors=true), so this is cheap when
        # nothing actually needed priming in phase 1.
        owned = [sd for sd in stage_detectors if not sd.is_external]
        if owned:
            logger.info("waiting for %d owned detector(s) to finish edge-pipeline training", len(owned))
            for sd in owned:
                num_labels = glh.num_priming_labels_for_detector(sd.detector)
                min_training_labels = int(num_labels * 0.75)
                glh.wait_for_edge_pipeline_trained(
                    self.gl_cloud, sd.detector, min_training_labels,
                    timeout_sec=glh.DEFAULT_TRAINING_SEC_TIMEOUT,
                )

        self._all_stage_detectors = stage_detectors
        return stage_detectors

    def _fetch_external(
        self,
        lens_name: str,
        stage: str,
        *,
        detector_id: str,
        expected_pipeline: str | None,
        copy_index: int = 0,
    ) -> StageDetector:
        """Fetch a pre-existing detector by ID, verify its pipeline
        matches the configured one, and return a StageDetector flagged
        is_external=True. Training and cleanup are skipped for the
        returned detector. The SDK has no way to override a detector's
        pipeline, so a config-vs-actual mismatch silently routes
        inference to the wrong model — we verify up front and fail
        loudly. External detectors are only valid at copy_index 0 with
        max_copies == 1 (enforced by the schema validator).
        """
        logger.info("fetching external detector %s for %s.%s", detector_id, lens_name, stage)
        det = self.gl_cloud.get_detector(detector_id)
        if expected_pipeline is not None:
            glh.assert_configured_edge_pipeline_matches_provided(
                self.gl_cloud, det.id, expected_pipeline,
            )
        return StageDetector(
            lens_name=lens_name, stage=stage, copy_index=copy_index,
            detector=det, detector_id=det.id, is_external=True,
        )

    def _provision(
        self,
        *,
        prefix: str,
        mode: str,
        image_size: tuple[int, int],
        pipeline: str | None,
        n: int | None,
        wait_for_training: bool = True,
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
            wait_for_training: When True (default), block until the edge
                pipeline finishes training. When False, return as soon as
                priming has been kicked off — caller is responsible for
                waiting (see provision_all's two-phase path).

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
            wait_for_training=wait_for_training,
        )
        self._all_created[det.name] = det
        return det

    @staticmethod
    def active_detectors_for_run(
        stage_detectors: list[StageDetector],
        lens_copies_for_run: dict[str, int],
    ) -> list[StageDetector]:
        """Subset of detectors that a given run actually exercises.

        A detector is active in a run iff its `copy_index` is below the
        run's copy count for that lens. Cameras don't affect the set —
        every camera of a lens-copy shares the same detector(s). The
        edge config is pushed per-run from this subset so the loaded
        detector count (and its VRAM / compute footprint) tracks the
        copies ramp instead of staying pinned at `max(copies)` the
        whole benchmark.

        Args:
            stage_detectors: Full provisioned set from provision_all().
            lens_copies_for_run: Mapping lens_name -> copy count for the
                run (from ResolvedRun.lens_copies).

        Returns:
            The active StageDetectors, preserving input order.
        """
        return [
            sd for sd in stage_detectors
            if sd.copy_index < lens_copies_for_run.get(sd.lens_name, 1)
        ]

    def push_edge_config(self, stage_detectors: list[StageDetector]) -> None:
        """Push an edge config containing ONLY the given benchmark
        detectors in NO_CLOUD mode. Called once per run with that run's
        active subset (see active_detectors_for_run) — the caller skips
        the push when the active set is unchanged from the previous run.

        This deliberately does NOT merge with the snapshotted pre-run
        config — pre-existing detectors are evicted for the duration of
        the benchmark so the measurement isn't contaminated by their
        GPU / CPU / RAM usage. `restore_edge_config` puts them back at
        cleanup; their pods will cold-start as Kubernetes reconciles the
        restored config. Applications that depend on the pre-existing
        detectors will see errors for the duration of the benchmark.

        The edge reconciles incrementally: detectors already loaded from
        the previous run's config stay warm (verified on G4 — same pod
        UID, no restart), so a ramp only cold-starts the newly-added
        copies. Blocks until inference pods report ready (or
        `set_config_timeout_seconds` elapses).

        Args:
            stage_detectors: The detectors to load for this run.
        """
        edge_config = EdgeEndpointConfig()
        for sd in stage_detectors:
            edge_config.add_detector(sd.detector, NO_CLOUD)
        self.gl_edge.edge.set_config(
            edge_config, timeout_sec=self.cfg.run.set_config_timeout_seconds,
        )

    def delete_all(self) -> tuple[int, int]:
        """Best-effort delete every detector we provisioned across all runs.

        External detectors (supplied via `*_detector_id` in the config)
        are NOT deleted — they were not created by the benchmark and
        the user expects them to persist. They are tracked separately
        on `_all_stage_detectors` with `is_external=True` and are not
        added to `_all_created` in the first place, so this filter is
        implicit.

        When `run.preserve_detectors` is True, ALL detectors we created
        are also preserved. Re-running the same config picks them up via
        `get_or_create_detector` and skips retraining if the edge
        pipeline is already sufficiently trained.

        Returns:
            (deleted_count, failed_count). Never raises — runs from
            atexit and we don't want to mask any prior exception.
        """
        external_count = sum(
            1 for sd in getattr(self, "_all_stage_detectors", [])
            if sd.is_external
        )
        if external_count:
            logger.info("skipping cleanup of %d external detector(s)", external_count)
        if self.cfg.run.preserve_detectors:
            logger.info(
                "preserve_detectors=true: keeping %d created detector(s) on the cloud "
                "for reuse on the next run",
                len(self._all_created),
            )
            return 0, 0
        deleted = failed = 0
        for det in self._all_created.values():
            try:
                self.gl_cloud.delete_detector(det.id)
                deleted += 1
            except Exception as exc:
                failed += 1
                logger.error("failed to delete %s: %s", det.id, exc)
        return deleted, failed
