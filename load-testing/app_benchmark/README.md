# app_benchmark — Lens-sweep benchmark for the edge-endpoint

A simplified harness that runs **three fixed lens shapes** concurrently and
**sweeps over the bbox `n` parameter** to characterize how throughput and
latency degrade as more crops are forwarded into a binary stage.

## Lens shapes

| `type` | Stages | `n`? | Per-frame work |
|---|---|---|---|
| `single_binary` | 1 binary call | no | binary inference on a pre-encoded synthetic JPEG |
| `single_bbox` | 1 bbox call | yes | bbox inference on a synthetic objects image bounded by `n` |
| `bbox_to_binary` | 1 bbox + N binary | yes | one bbox call, then N binary calls reusing one tiny pre-encoded JPEG |

For n-bearing lenses, the bbox detector is provisioned **once** with
`max_num_bboxes = max(lens.n)` and reused across every run in the sweep.
The per-run `n` only varies the worker's behavior:

- the synthetic image's object-count bound (`generate_random_objects_image(max_count=n)`), and
- for `bbox_to_binary`, the number of downstream binary calls issued per frame.

All lenses pre-encode a small JPEG pool at startup and cycle per frame —
keeps the per-iteration overhead minimal so you measure inference, not OpenCV.

### Per-lens overrides

`image_size` and `target_fps` can be set per-lens to override the `global:`
values. Anything left unset on a lens falls back to global. Set
`target_fps: 0` (either globally or per-lens) to disable pacing — the lens
will issue requests as fast as the edge can serve them.

## Run model

The config defines a list of lenses. Lenses with `type: single_bbox` or
`bbox_to_binary` carry an `n: [...]` list; that's the **sweep dimension**.

All `n` lists in the config must share the same length — they are **zipped**
across runs. With three lenses where two have `n=[2,4,6,8]` and `n=[1,3,5,7]`,
the harness produces 4 runs: `(n_a=2, n_b=1)`, `(n_a=4, n_b=3)`, etc.

Within each run, every lens runs its full `cameras` count in parallel as
independent OS processes.

**Detector lifecycle is one-shot, not per-run.** Each n-bearing lens
provisions a single bbox detector with `max_num_bboxes = max(lens.n)`
(the upper bound across the sweep) and trains it once before any run
starts. The per-run `n` value only controls:

- the synthetic image's object-count bound (`generate_random_objects_image(max_count=n)`), and
- for `bbox_to_binary` lenses, the number of downstream binary calls issued per frame.

The inference cost of the bbox model itself is essentially independent
of `max_num_bboxes` — the model processes the whole image regardless;
only NMS post-processing depends on detected count, which is negligible
relative to the convolutional cost.

## Hard dependencies

- Edge-endpoint includes PR #394 (`/status/resources.json` v2 shape).
- `GROUNDLIGHT_API_TOKEN` exported in the shell.
- Edge runs in Kubernetes (k3s) with x86 + ≥1 NVIDIA GPU.

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
- `--no-cleanup` — skip detector deletion + edge-config restore at end (debug only).

## Output

```
benchmark-results/{name}-{ts}/
├── summary.md                          # consolidated doc — primary view
├── summary.json                        # cross-run machine-readable
├── plots/                              # combined cross-run plots
│   ├── system_utilization.png          # 2x2 grid (CPU%, GPU%, RAM GB, VRAM GB)
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
  `Target`, `Hit`, `p50`, `p95` — and a ⚠ callout for any worker that
  exited non-zero or any camera that produced no events.

The FPS plots show frames-per-second on the left y-axis (blue), target FPS
as a dashed orange line, and failed requests / sec on a right y-axis (red).
For chained `bbox_to_binary` lenses, **frame** means one lens-loop iteration
(one bbox call + N binary calls); the errors axis counts all failed
**requests** across stages.

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
python -m app_benchmark.cleanup_edge --edge-endpoint http://EDGE:30101 --list
python -m app_benchmark.cleanup_edge --edge-endpoint http://EDGE:30101 --wipe
```

## Process topology

```
main                   (cli.py — orchestrates runs)
├─ SystemMonitor       (samples /status/resources.json on the edge)
└─ Σ lens.cameras workers across all lenses (per-camera frame loop)
```

For each run: workers run for `warmup + duration` seconds. The harness
drops a `RAMP <total_cameras>` marker after the warmup elapses; that
timestamp becomes `main_start_ts`, and `main_end_ts = main_start_ts +
duration` bounds the measurement window from above. After the duration
elapses, `_join_with_grace` waits for workers to exit and collects any
non-zero exit codes — these are surfaced as `worker_failures` in
`summary.json` and as a ⚠ callout in `summary.md`. Cameras that produced
no events at all get a flagged row in the per-run table.

Detectors are provisioned **once** at the start and reused across every
run (see "Detector lifecycle" above), so the run-to-run transition is
just workers exiting + new workers spawning; no detector retraining and
no edge-config swap between runs.
