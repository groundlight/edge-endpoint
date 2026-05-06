# Known Edge Pipeline Names

`mlpipe` (a.k.a. `edge_pipeline_config`) is a string ≤100 chars that names a
pipeline in the Groundlight cloud registry. Set `mlpipe: null` (or omit) to use
the detector type's default.

The list below is a starting point sourced from PR #373's
`benchmark_pipelines.example.yaml`. Verify against staging before pinning a
config to a specific pipeline.

## Bounding-box detectors

- `null` — mode default
- `groundlight-default-bounding-boxes-current`
- `bounding-boxes-step-rfdetr`
- `bounding-boxes-step-yolox`

## Binary detectors

- `null` — mode default

## Counting detectors

- `null` — mode default

## Multi-class detectors

- `null` — mode default

## Verifying

For a detector with a non-null `mlpipe`, the harness's Phase-2 detector
creation will call `provision_detector(...)` which internally invokes
`assert_configured_edge_pipeline_matches_provided` (see
`load-testing/groundlight_helpers.py:290`). If the cloud doesn't recognize the
pipeline name, the run aborts before any load is generated.
