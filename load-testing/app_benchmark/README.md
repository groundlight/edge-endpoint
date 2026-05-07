# app_benchmark — Edge-Endpoint Application Benchmarking Harness

Multi-process, YAML-driven harness for benchmarking the throughput of the
Groundlight edge-endpoint under realistic application shapes (single-detector
and chained `bbox → binary` pipelines, with multi-camera fan-out).

Companion design docs (gitignored): `.context/prd-edge-benchmark.md`,
`.context/tdd-edge-benchmark.md`.

## Hard dependencies

- Edge-endpoint includes PR #394 (`/status/resources.json` v2 shape).
- Groundlight cloud reachable for detector CRUD; `GROUNDLIGHT_API_TOKEN` set.
- Edge-endpoint runs in Kubernetes (k3s on the target hardware).
- x86 + ≥1 NVIDIA GPU.

## Installation

```bash
cd load-testing
uv sync
```

## Run a benchmark

```bash
cd load-testing
GROUNDLIGHT_API_TOKEN=... python -m app_benchmark configs/example_3lens.yaml
```

Flags:

- `--dry-run` — validate YAML, create detectors, register on edge, verify, then delete. No load generated.
- `--no-cleanup` — skip detector deletion at end (debugging only).

## Cleanup utilities

If a run is hard-killed (`kill -9`, OOM, or an old run before the
snapshot+restore fix), state can leak in two places:

**Cloud-side orphans** — detectors that were created but never deleted:

```bash
python -m app_benchmark.cleanup_orphans --prefix bench --dry-run
python -m app_benchmark.cleanup_orphans --prefix bench --older-than 1h
```

The prefix must be ≥4 characters; the script refuses short/empty prefixes.

**Edge-side orphans** — detector configs that the edge still has loaded
(inference pods running, even if the cloud detector was deleted):

```bash
# See what's loaded on the edge:
python -m app_benchmark.cleanup_edge --edge-endpoint http://EDGE:30101 --list

# Wipe everything (pushes an empty EdgeEndpointConfig):
python -m app_benchmark.cleanup_edge --edge-endpoint http://EDGE:30101 --wipe
```

## Output artifacts

Each run writes to `output_dir` (configured per-run, default
`./benchmark-results/{name}-{ts}/`):

| File | What |
|---|---|
| `summary.json` | Aggregate stats — FPS / latency / errors per lens, system totals, environment, control-plane verification. |
| `summary.md` | Human-readable summary table with WARNING lines for FPS deficit / errors / VRAM imbalance. |
| `metrics.csv` | One row per monitor sample (post-warmup). |
| `warmup.csv` | Same shape as `metrics.csv` but for the warmup window. |
| `lens_events.csv` | Per-frame and per-stage events. `stage_idx == -1` rows are end-of-frame summaries (used for FPS); `stage_idx >= 0` rows are per-POST events (used for latency / retries / errors). |
| `plots/fps_per_lens.png` | One subplot per lens, FPS over time, with `composite_objects_count` overlay (chained lenses). |
| `plots/fps_combined.png` | All lenses on shared axes — cross-lens contention view. |
| `plots/{vram,gpu_compute,ram,cpu}.png` | System-level time series. |
| `cleanup.log` | Detector creation / deletion audit. |
| `run.log` | JSON-lines harness log. |
| `config.resolved.json` | Validated config (defaults filled). |

## Key semantics

- **`cameras: N`** — spawns N independent OS processes for the lens. Each runs the same chain on the same shared detector(s); cameras don't synchronize.
- **`target_fps`** — per-camera, per **lens-loop iteration** (composite generation → all chain stages → emit FrameEvent). So `cameras: 4, target_fps: 5` ⇒ 20 lens-loops/sec aggregate.
- **Reported FPS** in `summary.json` and plots = lens-loop iterations / sec, **not** HTTP request rate. HTTP request rate = `aggregate_fps × (1 + num_crops_into_next)` for a 2-stage chain.
- **`mlpipe`** — string ≤100 chars referencing a named pipeline in the Groundlight cloud registry, or `null` for mode default. See `configs/known_pipelines.md`.
- **`composite_objects: null`** — chained lenses only — the composite contains a fresh `random[1, num_crops_into_next]` count of the base object per frame. Downstream stages always see exactly `num_crops_into_next` images: real ROIs from generation ground truth, padded with `padding_image` if fewer real objects were placed.
- **`error_budget_pct`** — per-client HTTP-error rate threshold (% over rolling 30 s window). Exceeding it kills that client and marks the lens DEGRADED.

## Process topology

```
main (cli.py)
├─ monitor process       (resource sampling via /status/resources.json)
└─ Σ lens.cameras client processes (per-camera composite + chain loop)
```

Stop semantics: SIGINT triggers orderly shutdown (clients finish in-flight,
monitor flushes, `atexit` deletes detectors). Two SIGINTs within 5 s force
exit. SIGKILL leaks detectors; recover via `cleanup_orphans`.

## Tests

```bash
cd load-testing
uv run pytest app_benchmark/tests
```

Integration tests against staging cloud + a local k3s edge are in
`app_benchmark/tests/integration/` and require `GROUNDLIGHT_API_TOKEN` plus
network access.
