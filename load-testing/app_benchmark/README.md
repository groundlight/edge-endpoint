# app_benchmark — Lens-sweep benchmark for the edge-endpoint

A simplified harness that runs **three fixed lens shapes** concurrently and
sweeps over a per-lens `n` parameter to characterize how throughput and
latency change as more crops are forwarded into a binary stage.

## Lens shapes

| `type` | Stages | `n`? | What `n` controls |
|---|---|---|---|
| `single_binary` | 1 binary call per frame | no | — |
| `single_bbox` | 1 bbox call per frame | yes | (a) the bbox detector's `max_num_bboxes`, set once to `max(lens.n)` at provisioning; (b) the synthetic image's **exact** object count — each frame contains exactly `n` placed objects |
| `bbox_to_binary` | 1 bbox + N binary calls per frame | yes | (a) the upstream bbox detector's `max_num_bboxes` = `max(lens.n)`; (b) the synthetic image's **exact** object count = the run's `n`; (c) the exact number of downstream binary calls issued per frame |

Workers generate a fresh synthetic image per frame via the helpers in
`load-testing/image_helpers.py` and pass the ndarray directly to
`gl.ask_ml` — the SDK handles JPEG encoding internally.

For `bbox_to_binary`, one small (224×224) binary image is generated once at
worker startup and resubmitted `n` times per frame; the SDK re-encodes per
call, which at that size is negligible.

### Per-lens overrides

`image_size` and `target_fps` can be set per-lens to override the `global:`
values. Anything left unset on a lens falls back to global. Set
`target_fps: 0` (either globally or per-lens) to disable pacing — the lens
will issue requests as fast as the edge can serve them.

`target_fps` is the *lens* iteration rate (one loop = 1 bbox + N binary for
chained lenses, or just 1 inference for single-stage). It is **not** a
per-stage rate.

## Run model

The config defines a list of lenses. Lenses with `type: single_bbox` or
`bbox_to_binary` carry an `n: [...]` list; that's the **sweep dimension**.

All `n` lists in the config must share the same length — they are **zipped**
across runs. With two lenses where one has `n=[2,4,6,8]` and the other
`n=[1,3,5,7]`, the harness produces 4 runs: `(n_a=2, n_b=1)`,
`(n_a=4, n_b=3)`, etc.

Within each run, every lens runs its full `cameras` count in parallel as
independent OS processes.

**Detector lifecycle is one-shot, not per-run.** Each n-bearing lens
provisions a single bbox detector with `max_num_bboxes = max(lens.n)` and
trains it once before any run starts. The per-run `n` value only affects
worker behavior — image synthesis bounds and, for chained lenses,
downstream call count.

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
GROUNDLIGHT_API_TOKEN=... python -m app_benchmark app_benchmark/configs/example.yaml
```

Flags:
- `--no-cleanup` — skip detector deletion + edge-config restore at end
  (debug only — leaves the edge in the merged state and detectors in the
  cloud).

## Output

```
benchmark_results/{name}-{ts}/
├── summary.md                          # consolidated doc — primary view
├── summary.json                        # cross-run machine-readable
├── plots/                              # combined cross-run plots
│   ├── system_utilization.png          # 2×2 grid (CPU%, GPU%, RAM GB, VRAM GB)
│   └── fps_{lens}_camera_{N}.png       # one per camera process
├── run_00/
│   ├── load_test.log                   # JSONL: request + cpu/gpu events
│   ├── summary.json                    # per-run machine-readable
│   └── plots/                          # per-run drill-down
│       ├── system_utilization.png
│       └── fps_{lens}_camera_{N}.png
├── run_01/...
└── ...
```

`summary.md` is the primary view. It contains:

- An environment block: run name, started_at, edge URL, ICMP **ping baseline**
  measured before the benchmark starts, and the global defaults.
- A cross-run overview table with per-lens mean FPS + Hit verdict per run
  (`yes` if every camera in the lens hit ≥95% of its target, `no` otherwise,
  `—` for saturate-mode lenses).
- Combined cross-run plots embedded inline. Each plot spans the whole
  benchmark wall-clock with vertical dotted lines + labels at each run's
  start. System plot labels: `Run i`. FPS plots: `Run i (n=X)` using
  that lens's own `n` for the run.
- Per-run sections with a per-camera table — `Frames`, `Errors`, `FPS`,
  `Target`, `Hit`, `p50`, `p95` — and a callout for any worker that
  exited non-zero or any camera that produced no events.

The FPS plots show frames-per-second on the left y-axis (blue), target FPS
as a dashed orange line, and failed requests / sec on a right y-axis (red).
The errors axis counts every failed **request** — for `bbox_to_binary`
each frame produces `1 + n` requests, any of which can be counted as a
failure independently of the lens's frame rate.

The measurement window is fixed at `[main_start_ts, main_start_ts +
duration)`. Events before `main_start_ts` (warmup) or at/after
`main_end_ts` (any in-flight or grace-period requests) are excluded from
the summary, so FPS reflects exactly `total_frames / duration`.

## Cleanup utilities

The benchmark cleans up its own detectors (cloud-side delete + edge-config
restore) at exit. If a run is hard-killed (`kill -9`, OOM) the cleanup
doesn't run — delete cloud detectors via the Groundlight dashboard and wipe
the edge-side stuck pods:

```bash
# List currently-configured detectors:
python -m app_benchmark.cleanup_edge --edge-endpoint http://EDGE:30101

# Wipe (asks for confirmation):
python -m app_benchmark.cleanup_edge --edge-endpoint http://EDGE:30101 --wipe

# Wipe without confirmation (scripted use):
python -m app_benchmark.cleanup_edge --edge-endpoint http://EDGE:30101 --wipe --force
```

## Process topology

```
main                   (cli.py — orchestrates runs)
├─ SystemMonitor       (samples /status/resources.json on the edge)
└─ Σ lens.cameras workers across all lenses (per-camera frame loop)
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
T5  delete benchX, benchY from cloud
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
