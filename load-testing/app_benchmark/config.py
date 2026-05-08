"""Schema and validation for the simplified app_benchmark config.

Three lens types are supported (single_binary, single_bbox, bbox_to_binary).
Lenses run concurrently inside each "run". Lenses that declare an `n` list
sweep across runs — all such lists must share the same length and are zipped
across lenses (run i uses element i from every n-list).
"""

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class ConfigError(Exception):
    pass


class RunConfig(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]+$", max_length=64)
    output_dir: str = "./benchmark-results/{name}-{ts}/"
    edge_endpoint_url: str
    cloud_endpoint: str = "https://api.groundlight.ai/"
    detector_name_prefix: str = Field(default="bench", pattern=r"^[a-z][a-z0-9_]{1,15}$")
    refuse_if_host_not_clean: bool = True
    set_config_timeout_seconds: int = Field(default=900, ge=30)


def _check_image_size(size: tuple[int, int]) -> None:
    w, h = size
    if w < 32 or h < 32 or w > 8192 or h > 8192:
        raise ValueError(f"image_size out of range: {size}")


class GlobalConfig(BaseModel):
    image_size: tuple[int, int] = (1920, 1080)
    target_fps: float = Field(default=5.0, ge=0)  # 0 = saturate (no pacing)
    duration_seconds: int = Field(default=180, ge=10)
    warmup_seconds: int = Field(default=20, ge=0)

    @model_validator(mode="after")
    def _check_resolution(self) -> "GlobalConfig":
        _check_image_size(self.image_size)
        return self


_LENS_NAME_PATTERN = r"^[a-zA-Z0-9_]+$"


class _LensBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=_LENS_NAME_PATTERN, max_length=64)
    cameras: int = Field(default=1, ge=1, le=64)
    image_size: tuple[int, int] | None = None
    target_fps: float | None = Field(default=None, ge=0)  # 0 = saturate (no pacing)

    @model_validator(mode="after")
    def _check_overrides(self) -> "_LensBase":
        if self.image_size is not None:
            _check_image_size(self.image_size)
        return self


class SingleBinaryLens(_LensBase):
    type: Literal["single_binary"]
    pipeline: str | None = Field(default=None, max_length=100)


class SingleBboxLens(_LensBase):
    type: Literal["single_bbox"]
    pipeline: str | None = Field(default=None, max_length=100)
    n: list[int] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_n(self) -> "SingleBboxLens":
        for value in self.n:
            if value < 1:
                raise ValueError(f"single_bbox.n entries must be >= 1 (got {value})")
        return self


class BboxToBinaryLens(_LensBase):
    type: Literal["bbox_to_binary"]
    bbox_pipeline: str | None = Field(default=None, max_length=100)
    binary_pipeline: str | None = Field(default=None, max_length=100)
    n: list[int] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_n(self) -> "BboxToBinaryLens":
        for value in self.n:
            if value < 1:
                raise ValueError(f"bbox_to_binary.n entries must be >= 1 (got {value})")
        return self


LensSpec = Annotated[
    SingleBinaryLens | SingleBboxLens | BboxToBinaryLens,
    Field(discriminator="type"),
]


class MonitoringConfig(BaseModel):
    sample_hz: float = Field(default=1.0, gt=0, le=20)


class BenchmarkConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    run: RunConfig
    globals_: GlobalConfig = Field(alias="global")
    lenses: list[LensSpec] = Field(min_length=1)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)


def validate_config(cfg: BenchmarkConfig) -> None:
    """Cross-lens invariants. Pydantic handles per-field rules; this catches
    the things that depend on the relationship between lenses."""
    names = [l.name for l in cfg.lenses]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ConfigError(f"duplicate lens names: {duplicates}")

    n_lists = [(l.name, l.n) for l in cfg.lenses if hasattr(l, "n")]
    if len(n_lists) >= 2:
        lengths = {len(ns) for _, ns in n_lists}
        if len(lengths) > 1:
            detail = ", ".join(f"{name}=len({len(ns)})" for name, ns in n_lists)
            raise ConfigError(
                f"all lens `n` lists must share the same length (they are zipped "
                f"across runs); got {detail}"
            )


def num_runs(cfg: BenchmarkConfig) -> int:
    """How many runs the config expands to (length of any `n` list, else 1)."""
    for lens in cfg.lenses:
        if hasattr(lens, "n"):
            return len(lens.n)
    return 1


def _format_validation_error(error: ValidationError) -> str:
    lines = [f"Configuration validation failed ({len(error.errors())} error(s)):"]
    for err in error.errors():
        loc = ".".join(str(p) for p in err.get("loc", ())) or "<root>"
        lines.append(f"  - {loc}: {err.get('msg')}")
    return "\n".join(lines)


def load_config(path: str | Path) -> BenchmarkConfig:
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"Config file not found: {path}")
    with path.open() as f:
        raw = yaml.safe_load(f)
    if raw is None:
        raise ConfigError(f"Empty config file: {path}")
    try:
        cfg = BenchmarkConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(exc)) from exc
    validate_config(cfg)
    return cfg
