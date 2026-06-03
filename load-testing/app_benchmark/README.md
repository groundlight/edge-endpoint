# app_benchmark — Lens-sweep benchmark for the edge-endpoint

A harness that runs **three fixed lens shapes** concurrently and sweeps
three independent dimensions across runs:

- **`objects`** per frame — how many objects appear in each synthetic image (and, for chained lenses, how many downstream binary calls run per frame).
- **`cameras`** per lens — how many independent worker processes hit the lens in parallel.
- **`copies`** per lens — how many independently-trained detector copies of the lens are active. Each copy is its own cloud-side detector with the same pipeline and `objects` setting; ramping copies measures how throughput scales with the number of distinct detectors the server is juggling.

All ramps are optional. When you don't ramp anything, the harness runs once. When you ramp one or more, every list in the config must share the same length — the dimensions are **zipped** (run `i` uses element `i` from every list).

## Lens shapes

| `type` | Stages | `objects`? | What `objects` controls |
|---|---|---|---|
| `single_binary` | 1 binary call per frame | no | — |
| `single_bbox` | 1 bbox call per frame | yes | (a) the bbox detector's `max_num_bboxes`, set once to `max(lens.objects)` at provisioning; (b) the synthetic image's **exact** object count — each frame contains exactly `objects` placed entities |
| `bbox_to_binary` | 1 bbox + `objects` binary calls per frame | yes | (a) the upstream bbox detector's `max_num_bboxes` = `max(lens.objects)`; (b) the synthetic image's **exact** object count; (c) the exact number of downstream binary calls issued per frame |

Workers generate a fresh synthetic image per frame via the helpers in
`load-testing/image_helpers.py` and pass the ndarray directly to
`gl.ask_ml` — the SDK handles JPEG encoding internally.

For `bbox_to_binary`, one small (224×224) binary image is generated once at
worker startup and resubmitted `objects` times per frame; the SDK re-encodes
per call, which at that size is negligible.

The `objects` downstream binary calls within a frame are submitted
**concurrently** (one bbox detect, then a parallel fan-out over the
ROIs across a thread pool, capped at 32 in-flight per worker). The ROIs
are independent, so parallelizing drives the edge to its real
throughput ceiling instead of serializing on per-request round-trip
latency. Frames stay sequential and `target_fps` still paces the whole
loop (1 bbox + N binary) as one unit — so a frame's wall-clock is
roughly `bbox_latency + max(binary_latencies)` rather than
`bbox_latency + objects × binary_latency`.

### Per-lens overrides

`image_size` and `target_fps` can be set per-lens to override the `global:`
values. Anything left unset on a lens falls back to global. Set
`target_fps: 0` (either globally or per-lens) to disable pacing — the lens
will issue requests as fast as the edge can serve them.

`target_fps` is the *lens* iteration rate (one loop = 1 bbox + `objects`
binary for chained lenses, or just 1 inference for single-stage). It is
**not** a per-stage rate.

## Run model — sweeps zip element-wise

Every list-typed field across the config (`objects`, `cameras`,
`copies`) is a sweep dimension. They are zipped together — all lists
must share the same length. Scalar values stay fixed across every run.

```yaml
lenses:
  - name: door_lens
    cameras: [1, 2, 4, 8]      # ramps camera count

  - name: person_lens
    objects: [2, 4, 6, 8]      # ramps objects per frame
    cameras: 1                 # fixed at 1

  - name: scaling_lens
    copies: [1, 2, 4, 8]       # ramps distinct detector copies
    cameras: 1
```

→ 4 runs. Run 0 = (door×1cam, person×1cam objects=2, scaling×1copy);
Run 3 = (door×8cam, person×1cam objects=8, scaling×8copies).

A 2×2 matrix is expressed by listing the cells explicitly:
```yaml
objects: [2, 2, 4, 4]
cameras: [1, 2, 1, 2]
```

Within each run, every lens runs `copies_for_run × cameras_for_run`
worker processes in parallel — one per (copy, camera) pair.

### `copies` semantics

For run `i`, the harness spawns workers against the first `copies[i]`
detectors of the lens (out of `max(copies)` provisioned at startup).
Each copy is a distinct cloud-side detector — same pipeline, same
`objects` setting, independently trained. So `copies` ramps "how many
detectors does the server handle", while `cameras` ramps "how many
workers per detector".

**Restriction**: `copies > 1` cannot be combined with `*_detector_id`.
A single pre-existing detector ID can't back multiple independently-
trained copies, so the schema validator rejects the combination
upfront.

## Detector lifecycle

**Two-phase provisioning, one-shot per benchmark.** Detectors are created
once before any run starts and reused for every run.

1. **Phase 1 (serial create + prime)** — each `(lens stage × copy)` is
   fetched (or created) by deterministic name, then primed with
   synthetic labels. The bbox detector's `max_num_bboxes` is set to
   `max(lens.objects)` so the same detector serves every run in the
   sweep. Copies > 1 multiply the per-stage detector count by
   `max(lens.copies)` and append a `_copy{k}` suffix to each
   detector's deterministic name.
2. **Phase 2 (parallel training wait)** — workers serially poll each
   detector's edge-pipeline training status. Because training is happening
   cloud-side after phase 1's priming, all detectors train in parallel
   during these waits. Total wall-clock is dominated by the slowest
   single detector, not the sum.

This mirrors PR #373's `provision_detectors` pattern but uses per-lens
prefixes so detector names stay distinct.

### Using pre-existing detectors (`*_detector_id`)

Any lens stage can be backed by a pre-existing cloud detector instead of
creating + training one. Set the appropriate ID:

```yaml
- name: production_door
  type: single_binary
  pipeline: generic-cached-timm-efficientnetv2s-calibrated-mlp
  binary_detector_id: det_2abc123XYZ
  cameras: 1

- name: hybrid_chain
  type: bbox_to_binary
  bbox_pipeline: bounding-boxes-step-rfdetr-primed
  binary_pipeline: generic-cached-timm-efficientnetv2s-calibrated-mlp
  bbox_detector_id: det_4def456ABC    # existing bbox stage
  # binary_detector_id omitted → harness trains a fresh binary detector
  objects: [2, 4]
  cameras: 1
```

The harness fetches the detector by ID, **verifies** its actual cloud-side
pipeline matches the `pipeline:` declared in the YAML, and skips creation
+ training. The detector is also preserved at cleanup. Edge inference still
runs in `NO_CLOUD` mode so the existing detector's training data isn't
polluted.

A pipeline mismatch fails fast with both pipelines printed inline — before
any edge config is pushed — so silent routing to the wrong model isn't
possible.

### Preserving owned detectors across runs

Set `run.preserve_detectors: true` to skip cloud-side deletion of detectors
the harness created. Re-runs of the same config hit `get_or_create_detector`
and reuse the existing detectors, skipping retraining when the edge pipeline
is already sufficiently trained. Pipeline mismatches are still caught:
changing `pipeline:` in the YAML between runs fails fast on the next run.

External (`*_detector_id`) detectors are always preserved regardless of
this flag.

## Hard dependencies

- `/status/resources.json` v2 shape on the edge (in `main` since PR #394).
- `GROUNDLIGHT_API_TOKEN` exported in the shell.
- Edge endpoint reachable at the configured URL. The edge should have a
  CUDA-capable GPU for realistic numbers; CPU works for sanity checks but
  isn't representative.

## Install

```bash
cd load-testing
uv sync
```

## Run

```bash
cd load-testing
GROUNDLIGHT_API_TOKEN=... uv run app_benchmark app_benchmark/configs/example.yaml
```

(The longer form `uv run --python 3.13 python -m app_benchmark <config>`
still works if you prefer to pin the interpreter explicitly.)

Flags:
- `--no-cleanup` — skip detector deletion + edge-config restore at end
  (debug only — leaves the edge in the merged state and detectors in the
  cloud).

## Output

```
benchmark_results/{name}-{ts}/
├── summary.md                          # consolidated doc — primary view
├── summary.json                        # cross-run machine-readable
├── plots/                              # cross-run plots
│   ├── system_utilization.png          # 2×2 grid (CPU%, GPU%, RAM GB, VRAM GB)
│   ├── fps_all_lenses.png              # 2-column mosaic of per-lens overlays
│   ├── fps_{lens}.png                  # per-lens overlay, cameras OR copies as colored lines
│   └── per_camera/                     # per-(lens, copy, camera) detail (files only)
│       └── fps_{lens}[_copy{k}]_camera_{N}.png
├── run_00/
│   ├── system.log                      # JSONL: cpu/gpu events (SystemMonitor)
│   ├── camera_{lens}_{N}.log           # JSONL: request events, one file per camera process
│   ├── summary.json                    # per-run machine-readable
│   └── plots/                          # per-run drill-down
│       ├── system_utilization.png
│       └── fps_{lens}_camera_{N}.png
├── run_01/...
└── ...
```

`summary.md` is the primary view. It contains:

- **Environment block** — run name, started_at, edge URL, ICMP **ping
  baseline** measured before the benchmark starts, and the global defaults.
- **Lens configuration table** — resolved per-lens config: pipeline,
  detector ID (with `(external)` tag for pre-existing detectors, or
  `(+N more)` when copies > 1), camera count, copy count, objects.
  The authoritative "what actually ran" record.
- **Overview table** — one row per run with per-lens mean FPS + Hit
  verdict (`yes` if every camera in the lens hit ≥95% of its target,
  `no` otherwise, `—` for saturate-mode lenses). Gets a `lens_cameras`
  column when any lens has a cameras ramp, and a `lens_copies` column
  when any lens has a copies ramp.
- **Cross-run system utilization** — 2×2 plot spanning the whole benchmark.
- **Cross-run FPS overview** — mosaic image showing every lens at a
  glance. Each cell is one lens; the colored lines are either
  **cameras** (when the lens has no copies ramp) or **copies** (when
  it does) — the dimension that's varying gets the focus. Viridis
  colormap (blue → yellow). Lines that only existed in later runs
  start partway through the time axis — visualizes the scaling story
  directly.
- **Per-lens detail** — one larger plot per lens, same overlay layout.
  Aggregated failed-requests rate (sum across all workers of the lens)
  on a secondary axis in red.
- **Per-run sections** — per-worker table with `Lens`, `Copy`, `Camera`,
  `Frames`, `Errors`, `FPS`, `Target`, `Hit`, `p50`, `p95`; callouts
  for any worker that exited non-zero or any worker that produced no
  events.

Per-(lens, copy, camera) detail PNGs are still written to
`plots/per_camera/` for ad-hoc deep dives — they're just no longer
embedded in `summary.md` (the per-lens overlay covers the common
case). Filenames are `fps_{lens}_camera_{N}.png` when copies are
constant (back-compat) and `fps_{lens}_copy{k}_camera_{N}.png` when
any lens ramps copies. The per-camera subfolder keeps the top-level
`plots/` clean: only the summary-relevant plots
(`fps_all_lenses.png`, `fps_{lens}.png`, `system_utilization.png`) sit
at the top, with the high-cardinality detail files tucked one level
down.

Plot boundary labels read `Run i (objects=X)` when `objects` varies, and
add `, cams=Y` when `cameras` also varies across runs.

The measurement window is fixed at `[main_start_ts, main_start_ts +
duration)`. Events before `main_start_ts` (warmup) or at/after
`main_end_ts` (any in-flight or grace-period requests) are excluded from
the summary, so FPS reflects exactly `total_frames / duration`.

## Cleanup utilities

The benchmark cleans up its own detectors (cloud-side delete + edge-config
restore) at exit. External (`*_detector_id`) and `preserve_detectors: true`
detectors skip the delete. If a run is hard-killed (`kill -9`, OOM) the
cleanup doesn't run — delete cloud detectors via the Groundlight dashboard
and wipe the edge-side stuck pods:

```bash
# List currently-configured detectors:
uv run python -m app_benchmark.cleanup_edge --edge-endpoint http://EDGE:30101

# Wipe (asks for confirmation):
uv run python -m app_benchmark.cleanup_edge --edge-endpoint http://EDGE:30101 --wipe

# Wipe without confirmation (scripted use):
uv run python -m app_benchmark.cleanup_edge --edge-endpoint http://EDGE:30101 --wipe --force
```

## Process topology

```
main                       (cli.py — orchestrates runs)
├─ SystemMonitor           (samples /status/resources.json on the edge)
└─ Σ cameras_for_run workers across all lenses (per-camera frame loop)
```

For each run: workers run for `warmup + duration` seconds. After the warmup
elapses we record `main_start_ts`; `main_end_ts = main_start_ts + duration`
bounds the measurement window from above. `_join_with_grace` waits for
workers to exit and collects any non-zero exit codes — these are surfaced
as `worker_failures` in `summary.json` and as a callout in `summary.md`.
Cameras that produced no events at all get a flagged row in the per-run
table.

Detectors are provisioned **once** at the start and reused across every
run, so the run-to-run transition is just workers exiting + new workers
spawning; no detector retraining and no edge-config swap between runs.

## Host check and edge-config lifecycle

The benchmark always pushes an edge config that contains **only** its own
detectors. Any pre-existing detectors are evicted for the duration of the
run and restored at cleanup. This keeps the measurement clean — pre-existing
detectors don't contaminate GPU / CPU / RAM during the benchmark — at the
cost of disrupting any application using them while the benchmark runs.

Sequence:

```
T0  edge: [detA, detB]                          ← whatever was there
T1  snapshot captures [detA, detB]
T2  push ONLY ours: edge ← [benchX, benchY]     ← detA, detB pods torn down
T3  benchmark runs against a clean edge
T4  restore snapshot: edge ← [detA, detB]       ← detA, detB pods cold-start back
T5  delete benchX, benchY from cloud (skipped for external + preserve_detectors)
```

By default the benchmark logs a warning and proceeds when the edge already
has detectors loaded; expect those detectors' applications to error between
T2 and T4. Set `run.refuse_if_host_not_clean: true` to hard-fail instead —
the right choice for CI, shared edges, or any context where eviction would
break someone.

Caveat: the restore at T4 only runs if `atexit` fires (normal exit,
exception, SIGINT, SIGTERM). A `kill -9` or OOM leaves the edge in the
benchmark-only state; recover with `cleanup_edge.py --wipe` followed by
re-applying the host's real config.
