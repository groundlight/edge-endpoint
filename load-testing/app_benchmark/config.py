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
    """Raised by load_config / validate_config when a YAML config fails any
    schema or cross-lens validation rule."""


class RunConfig(BaseModel):
    """Top-level run settings (everything under the YAML `run:` block).

    Attributes:
        name: Benchmark identifier; appears in output_dir, detector names,
            and summary.md. Restricted to [a-zA-Z0-9_-], max 64 chars.
        output_dir: Where artifacts get written. `{name}` and `{ts}` are
            substituted at runtime. Default puts everything under
            `./benchmark_results/{name}-{ts}/` so the root .gitignore
            (which ignores `load-testing/benchmark_results/`) covers it.
        edge_endpoint_url: HTTP(S) URL of the edge endpoint under test.
        cloud_endpoint: Groundlight cloud URL used for detector CRUD.
        detector_name_prefix: Optional short prefix (≤16 chars, lowercase,
            must start with a letter) that all created detectors carry.
            When None, derived automatically from `name` (lowercased,
            dashes → underscores, truncated to 16 chars). Used by the
            cloud dashboard / cleanup flows to identify benchmark
            detectors.
        refuse_if_host_not_clean: If True, refuse to start when the edge
            already has detectors configured. Default False — we log a
            warning and proceed, since `edge.set_config` merges cleanly
            and restores the pre-run state at cleanup. Set True for CI
            or any context where contamination is unacceptable.
        set_config_timeout_seconds: How long to wait for `edge.set_config`
            to finish (cold edges with many models need more).
    """
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]+$", max_length=64)
    output_dir: str = "./benchmark_results/{name}-{ts}/"
    edge_endpoint_url: str
    cloud_endpoint: str = "https://api.groundlight.ai/"
    detector_name_prefix: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{1,15}$")
    refuse_if_host_not_clean: bool = False
    set_config_timeout_seconds: int = Field(default=900, ge=30)

    @model_validator(mode="after")
    def _derive_prefix(self) -> "RunConfig":
        if self.detector_name_prefix is None:
            # Slug the name into the prefix shape: lowercase, dashes→underscores,
            # strip anything outside [a-z0-9_], truncate to 16 chars, ensure
            # it starts with a letter (fall back to "bench" if not).
            slug = "".join(
                c for c in self.name.lower().replace("-", "_")
                if c.isalnum() or c == "_"
            )[:16]
            if not slug or not slug[0].isalpha():
                slug = "bench"
            # Replicate the validator that's enforced when the user sets it
            # explicitly — must be ≥2 chars to satisfy the {1,15} length tail.
            if len(slug) < 2:
                slug = (slug + "bench")[:16]
            self.detector_name_prefix = slug
        return self


def _check_image_size(size: tuple[int, int]) -> None:
    """Raise ValueError if (width, height) is outside [32, 8192] in either dim."""
    w, h = size
    if w < 32 or h < 32 or w > 8192 or h > 8192:
        raise ValueError(f"image_size out of range: {size}")


class GlobalConfig(BaseModel):
    """Per-benchmark defaults (YAML key `global`, aliased to `globals_` in
    Python since `global` is a keyword). Any lens may override `image_size`
    or `target_fps`; the rest are run-wide.

    Attributes:
        image_size: (width, height) in pixels for the synthetic images each
            worker generates. Bounded to [32, 8192] in each dimension.
        target_fps: Per-camera frame rate target. 0 disables pacing
            (saturate — workers issue requests as fast as the edge serves).
        duration_seconds: Length of the measurement window for each run
            (excluding warmup). Events at or after main_start_ts + duration
            are excluded from the summary.
        warmup_seconds: Time the workers run before the measurement window
            opens. Lets caches warm up and inference pods spin to steady
            state before we start counting.
    """
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
    """Fields shared by every lens type. Subclasses add `type` (the
    discriminator) plus the pipeline/n fields specific to their shape.

    Attributes:
        name: Lens identifier; appears in detector names, log records,
            plot filenames, and summary tables.
        cameras: How many independent worker processes to run for this
            lens. Each camera generates and submits its own frames.
        image_size: Optional override for this lens; falls back to global
            image_size when None.
        target_fps: Optional override; falls back to global target_fps.
            0 means saturate (no pacing).
    """
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
    """One binary inference per frame. Workers generate a synthetic
    black/white image with a timestamp overlay and submit it.

    Attributes:
        pipeline: Optional Groundlight pipeline config name. None uses
            the cloud's default binary pipeline.
    """
    type: Literal["single_binary"]
    pipeline: str | None = Field(default=None, max_length=100)


class SingleBboxLens(_LensBase):
    """One bounding-box inference per frame. The synthetic image contains
    up to `n` random objects (count varies per frame), and the bbox
    detector is provisioned with `max_num_bboxes = max(n)`.

    Attributes:
        pipeline: Optional Groundlight pipeline config name. None uses
            the cloud's default bbox pipeline.
        n: List of integer values to sweep across runs. Zipped with other
            lenses' n lists; must share the same length when multiple
            lenses declare n.
    """
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
    """Chained inference: 1 bbox call + N binary calls per frame. Models a
    "detect objects, then classify each ROI" pipeline. Each frame submits
    the bbox image once and then resubmits a small cached binary image N
    times.

    Attributes:
        bbox_pipeline: Optional pipeline config for the bbox stage.
        binary_pipeline: Optional pipeline config for the downstream
            binary stage.
        n: List of integer values to sweep across runs. n controls BOTH
            the bbox detector's `max_num_bboxes` (set to max(n) once at
            provisioning) AND the number of downstream binary calls
            issued per frame in this run.
    """
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


# Pydantic discriminated union — picks the right subclass based on the
# `type` field in YAML.
LensSpec = Annotated[
    SingleBinaryLens | SingleBboxLens | BboxToBinaryLens,
    Field(discriminator="type"),
]


class MonitoringConfig(BaseModel):
    """SystemMonitor polling parameters.

    Attributes:
        sample_hz: How often (Hz) to poll /status/resources.json on the
            edge. CPU/RAM are bounded by k8s Metrics Server cadence (~15s)
            so values above 1Hz give repeated CPU/RAM samples but fresher
            GPU/VRAM numbers.
    """
    sample_hz: float = Field(default=1.0, gt=0, le=20)


class BenchmarkConfig(BaseModel):
    """Root config object built from the YAML file.

    Attributes:
        run: Top-level run settings (name, URLs, output dir, etc.).
        globals_: Per-benchmark defaults. YAML key is `global`; Python
            access uses `globals_` because `global` is a keyword.
        lenses: List of lens specs. Each runs concurrently within every
            run; lenses that declare `n` define the sweep dimension.
        monitoring: SystemMonitor sampling settings.
    """
    model_config = ConfigDict(populate_by_name=True)
    run: RunConfig
    globals_: GlobalConfig = Field(alias="global")
    lenses: list[LensSpec] = Field(min_length=1)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)


def validate_config(cfg: BenchmarkConfig) -> None:
    """Cross-lens invariants that don't fit inside a single Pydantic model.

    Pydantic already enforces per-field rules; this function catches
    relationships between lenses that need a whole-config view.

    Args:
        cfg: The Pydantic-validated config object.

    Raises:
        ConfigError: When two lenses share a name, or when two or more
            lenses declare `n` lists of different lengths.
    """
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
    """Return the number of runs this config expands to.

    Args:
        cfg: A validated BenchmarkConfig.

    Returns:
        len(lens.n) for any lens that declares n (all n lists share a
        length per validate_config), or 1 when no lens has n.
    """
    for lens in cfg.lenses:
        if hasattr(lens, "n"):
            return len(lens.n)
    return 1


def _format_validation_error(error: ValidationError) -> str:
    """Build a human-readable summary of a Pydantic ValidationError."""
    lines = [f"Configuration validation failed ({len(error.errors())} error(s)):"]
    for err in error.errors():
        loc = ".".join(str(p) for p in err.get("loc", ())) or "<root>"
        lines.append(f"  - {loc}: {err.get('msg')}")
    return "\n".join(lines)


def load_config(path: str | Path) -> BenchmarkConfig:
    """Parse a YAML config file and run all validators.

    Args:
        path: Filesystem path to the YAML config.

    Returns:
        Fully-validated BenchmarkConfig — Pydantic field rules AND
        validate_config's cross-lens checks have already passed.

    Raises:
        ConfigError: File missing, empty, fails Pydantic validation, or
            fails any cross-lens invariant.
    """
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
