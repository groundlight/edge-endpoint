"""Detector lifecycle: cloud-side create + edge-side register + cleanup.

Wraps existing helpers in load-testing/groundlight_helpers.py — does NOT reimplement.
"""

import logging
from dataclasses import dataclass

from groundlight import Detector, ExperimentalApi
from groundlight.edge import NO_CLOUD

import groundlight_helpers as glh
from app_benchmark.config import BenchmarkConfig, DetectorSpec, RunConfig

logger = logging.getLogger(__name__)


@dataclass
class CreatedDetector:
    spec_name: str
    cloud_name_prefix: str
    detector_id: str
    detector: Detector


_TYPE_TO_MODE = {
    "bounding_box": "BOUNDING_BOX",
    "binary": "BINARY",
    "multi_class": "MULTI_CLASS",
    "count": "COUNT",
}


def _name_prefix(run: RunConfig, spec: DetectorSpec) -> str:
    """Cloud detector name prefix.

    `provision_detector` will append " {W} x {H} - {MODE} - n{n} - {hash}" to
    this prefix. We use the prefix for orphan-cleanup matching.
    """
    return f"{run.detector_name_prefix}_{run.name}_{spec.name}"


class DetectorManager:
    def __init__(self, cfg: BenchmarkConfig, gl_cloud: ExperimentalApi, gl_edge: ExperimentalApi) -> None:
        self.cfg = cfg
        self.gl_cloud = gl_cloud
        self.gl_edge = gl_edge

    def create_all(self) -> list[CreatedDetector]:
        seen: dict[str, CreatedDetector] = {}
        for spec in self.cfg.detectors:
            if spec.name in seen:
                continue
            mode = _TYPE_TO_MODE[spec.type]
            prefix = _name_prefix(self.cfg.run, spec)
            logger.info("creating detector %r (mode=%s, mlpipe=%r)", spec.name, mode, spec.mlpipe,
                        extra={"phase": "detector_create"})
            detector = glh.provision_detector(
                self.gl_cloud,
                detector_mode=mode,
                detector_name_prefix=prefix,
                image_width=spec.image_width,
                image_height=spec.image_height,
                edge_pipeline_config=spec.mlpipe,
                n=spec.n,
            )
            seen[spec.name] = CreatedDetector(
                spec_name=spec.name,
                cloud_name_prefix=prefix,
                detector_id=detector.id,
                detector=detector,
            )
            logger.info("created detector %s -> %s", spec.name, detector.id,
                        extra={"phase": "detector_create", "detector_id": detector.id})
        return list(seen.values())

    def register_on_edge(self, created: list[CreatedDetector]) -> None:
        if not created:
            return
        logger.info("registering %d detector(s) on edge in NO_CLOUD mode (set_config blocks until ready)",
                    len(created), extra={"phase": "edge_config"})
        glh.configure_edge_endpoint(
            self.gl_edge,
            [c.detector for c in created],
            edge_inference_config=NO_CLOUD,
        )
        logger.info("edge configured", extra={"phase": "edge_config"})

    def delete_all(self, created: list[CreatedDetector]) -> tuple[int, int]:
        """Best-effort delete; returns (deleted, failed). Never raises."""
        deleted, failed = 0, 0
        for c in created:
            try:
                self.gl_cloud.delete_detector(c.detector_id)
                deleted += 1
                logger.info("deleted detector %s", c.detector_id,
                            extra={"phase": "cleanup", "detector_id": c.detector_id})
            except Exception as exc:
                failed += 1
                logger.error("failed to delete detector %s: %s", c.detector_id, exc,
                             extra={"phase": "cleanup", "detector_id": c.detector_id})
        return deleted, failed
