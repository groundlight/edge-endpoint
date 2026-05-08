# app_benchmark — Lens-sweep benchmark for the edge-endpoint

A simplified harness that runs **three fixed lens shapes** concurrently and
**sweeps over the bbox `n` parameter** to characterize how throughput and
latency degrade as more crops are forwarded into a binary stage.

## Lens shapes

| `type` | Stages | `n`? | Per-frame work |
|---|---|---|---|
| `single_binary` | 1 binary call | no | binary inference on a pre-encoded synthetic JPEG |
| `single_bbox` | 1 bbox call | yes (sets `max_num_bboxes`) | bbox inference on a synthetic objects image |
| `bbox_to_binary` | 1 bbox + N binary | yes (sets `max_num_bboxes` AND number of downstream calls) | one bbox call, then N binary calls reusing one tiny pre-encoded JPEG |

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
independent OS processes. The bbox `n` for that run sets the detector's
`max_num_bboxes` (so the inference cost varies) and, for `bbox_to_binary`,
also controls how many downstream binary calls are issued per frame.

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
├── summary.json         # cross-run aggregate (one row per n-step)
├── summary.md           # human-readable cross-run table
├── run_00/
│   ├── load_test.log    # JSONL: request events + cpu/gpu samples
│   ├── summary.json
│   ├── summary.md
│   └── plots/
│       ├── requests_per_second.png
│       └── system_utilization.png
├── run_01/...
└── ...
```

The per-run `summary.{json,md}` reports per-lens RPS, error count, and
p50/p95 latency over the post-warmup window. Cross-run `summary.md`
tabulates aggregate + per-lens RPS as `n` sweeps.

## Cleanup utilities

If a run is hard-killed (`kill -9`, OOM):

```bash
# Cloud-side orphan detectors:
python -m app_benchmark.cleanup_orphans --prefix bench --dry-run
python -m app_benchmark.cleanup_orphans --prefix bench --older-than 1h

# Edge-side stuck pods:
python -m app_benchmark.cleanup_edge --edge-endpoint http://EDGE:30101 --list
python -m app_benchmark.cleanup_edge --edge-endpoint http://EDGE:30101 --wipe
```

## Process topology

```
main                   (cli.py — orchestrates runs)
├─ SystemMonitor       (samples /status/resources.json)
└─ Σ lens.cameras workers across all lenses (per-camera frame loop)
```

For each run: workers run for `warmup + duration` seconds. The harness drops
a `RAMP <total_cameras>` marker after the warmup elapses, and the report
filters request events to `ts >= main_start_ts` so warmup is excluded from
the throughput / latency stats.
