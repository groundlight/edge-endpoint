from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator
from ruamel.yaml import YAML

DetectorType = Literal["bounding_box", "binary", "multi_class", "count"]


class ConfigError(Exception):
    pass


class RunConfig(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]+$", max_length=64)
    duration_seconds: int = Field(default=600, ge=10)
    warmup_seconds: int = Field(default=30, ge=0)
    output_dir: str = "./benchmark-results/{name}-{ts}/"
    edge_endpoint_url: str
    set_config_timeout_seconds: int = Field(default=900, ge=30)
    cloud_endpoint: str = "https://api.groundlight.ai/"
    detector_name_prefix: str = Field(default="bench", pattern=r"^[a-z][a-z0-9_]{1,15}$")
    refuse_if_host_not_clean: bool = True


class DetectorSpec(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_]+$", max_length=64)
    type: DetectorType
    mlpipe: str | None = Field(default=None, max_length=100)
    n: int | None = Field(default=None, ge=1)
    image_width: int = Field(default=640, ge=32, le=8192)
    image_height: int = Field(default=480, ge=32, le=8192)


class ChainStage(BaseModel):
    detector: str
    num_crops_into_next: int = Field(default=1, ge=1)


class ImageConfig(BaseModel):
    base: str
    resolution: tuple[int, int]
    composite_objects: int | None = Field(default=None, ge=1)
    seed: int = 42

    @model_validator(mode="after")
    def _check_resolution(self) -> "ImageConfig":
        w, h = self.resolution
        if w < 32 or h < 32 or w > 8192 or h > 8192:
            raise ValueError(f"image.resolution out of range: {self.resolution}")
        return self


class DownstreamCropConfig(BaseModel):
    resize_to: tuple[int, int]
    padding_image: str

    @model_validator(mode="after")
    def _check_resize(self) -> "DownstreamCropConfig":
        w, h = self.resize_to
        if w < 16 or h < 16 or w > 4096 or h > 4096:
            raise ValueError(f"downstream_crop.resize_to out of range: {self.resize_to}")
        return self


class LensSpec(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_]+$")
    chain: list[ChainStage] = Field(min_length=1)
    target_fps: float = Field(ge=0)
    cameras: int = Field(default=1, ge=1, le=64)
    image: ImageConfig
    downstream_crop: DownstreamCropConfig | None = None
    error_budget_pct: float = Field(default=1.0, ge=0, le=100)

    @model_validator(mode="after")
    def _check_image_consistency(self) -> "LensSpec":
        is_chained = len(self.chain) > 1

        for i, stage in enumerate(self.chain):
            is_terminal = i == len(self.chain) - 1
            if is_terminal and stage.num_crops_into_next != 1:
                raise ValueError(
                    f"lens {self.name!r} stage {i}: num_crops_into_next is only valid on non-terminal stages"
                )

        if is_chained and self.downstream_crop is None:
            raise ValueError(f"lens {self.name!r}: chained lens requires downstream_crop block")
        if not is_chained and self.image.composite_objects is None:
            raise ValueError(
                f"lens {self.name!r}: single-stage lens requires explicit image.composite_objects "
                f"(no num_crops_into_next to derive from)"
            )
        return self


class MonitoringConfig(BaseModel):
    sample_hz: float = Field(default=2.0, gt=0, le=20)
    steady_state_window_seconds: int = Field(default=10, ge=2)


class BenchmarkConfig(BaseModel):
    schema_version: Literal[1]
    run: RunConfig
    detectors: list[DetectorSpec] = Field(min_length=1)
    lenses: list[LensSpec] = Field(min_length=1)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)

    @model_validator(mode="after")
    def _check_chain_refs(self) -> "BenchmarkConfig":
        det_names = {d.name for d in self.detectors}
        for lens in self.lenses:
            for i, stage in enumerate(lens.chain):
                if stage.detector not in det_names:
                    raise ValueError(
                        f"lens {lens.name!r} stage {i}: unknown detector {stage.detector!r} (known: {sorted(det_names)})"
                    )
        return self


def _annotate_with_yaml_marks(error: ValidationError, raw: Any) -> str:
    lines = [f"Configuration validation failed ({len(error.errors())} error(s)):"]
    for err in error.errors():
        loc = err.get("loc", ())
        line = _resolve_line(raw, loc)
        loc_path = ".".join(str(p) for p in loc) or "<root>"
        suffix = f" (line {line})" if line is not None else ""
        lines.append(f"  - {loc_path}{suffix}: {err.get('msg')}")
    return "\n".join(lines)


def _resolve_line(node: Any, loc: tuple[Any, ...]) -> int | None:
    cursor = node
    last_lc = getattr(cursor, "lc", None)
    for key in loc:
        if isinstance(cursor, dict) and key in cursor:
            child_lc = getattr(cursor, "lc", None)
            if child_lc is not None and hasattr(child_lc, "data") and key in (child_lc.data or {}):
                pos = child_lc.data[key]
                if pos and len(pos) >= 1:
                    last_lc = type("LC", (), {"line": pos[0]})()
            cursor = cursor[key]
        elif isinstance(cursor, list) and isinstance(key, int) and 0 <= key < len(cursor):
            cursor = cursor[key]
            child_lc = getattr(cursor, "lc", None)
            if child_lc is not None:
                last_lc = child_lc
        else:
            break
    line = getattr(last_lc, "line", None)
    return line + 1 if isinstance(line, int) else None


def load_config(path: str | Path) -> BenchmarkConfig:
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"Config file not found: {path}")
    yaml = YAML(typ="rt")
    with path.open() as f:
        raw = yaml.load(f)
    if raw is None:
        raise ConfigError(f"Empty config file: {path}")
    try:
        return BenchmarkConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(_annotate_with_yaml_marks(exc, raw)) from exc
