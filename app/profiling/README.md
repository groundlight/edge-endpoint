# Profiling System

The edge-endpoint includes an opt-in request-level tracing system that records per-stage timing for every inference request as JSONL to disk.

## Enabling Profiling

### Helm deployment

```bash
helm upgrade -i edge-endpoint ... --set enableProfiling=true
```

### Environment variable

```bash
ENABLE_PROFILING=true
```

When enabled, the profiling middleware creates a trace per request. Functions decorated with `@trace_span` automatically create child spans. Traces are written as JSONL to `/opt/groundlight/device/edge-profiling/` with 5-minute file rotation and 24-hour automatic cleanup.

## Traced Spans

```
request                              <- middleware (full request lifecycle)
+-- get_detector_metadata            <- cache hit vs cloud API round-trip
+-- inference_is_available           <- health check cache hit vs cold check
+-- _submit_primary_inference        <- HTTP to primary inference pod
+-- _submit_oodd_inference           <- HTTP to OODD inference pod (parallel)
+-- get_inference_result             <- result parsing + OODD confidence adjustment
+-- write_escalation_to_queue        <- disk write for background/audit escalation (on request path)
+-- safe_escalate_with_queue_write   <- synchronous cloud escalation (when triggered)
```

## Profiling Dashboard

A [Marimo](https://marimo.io/) notebook provides interactive visualization of trace data.

### Prerequisites

Marimo and plotly live in an **optional** `profiling` dependency group, so they are **not** installed by default. To install them:

```bash
poetry install --with profiling
```

This keeps the ~50MB of dashboard dependencies out of everyone else's environment while letting anyone who wants the dashboard opt in.

> **Note**: The production Docker image is built with `--without dev --without lint` (and does not include the `profiling` group either), so marimo is **not** installed in the `edge-endpoint` container. To view traces from a device, copy the trace files to your workstation (see [Custom Trace Data Directory](#custom-trace-data-directory)) or run `poetry install --with profiling` inside the container before launching the dashboard.

### Launching the Dashboard

From the repo root:

```bash
poetry run marimo run app/profiling/dashboard.py
```

Marimo starts a web server on port 2718 (or the next open port if that's in use) and prints the URL. The dashboard is **read-only** in `run` mode — to edit cells, use `marimo edit` (see [Editing the Notebook](#editing-the-notebook) below). Stop the server with `Ctrl+C`.

### On an Edge Device

After installing dev dependencies (see Prerequisites), SSH into the device or exec into the `edge-endpoint` container, then:

```bash
# --host 0.0.0.0 makes the dashboard reachable from outside the container.
# --port is arbitrary; pick any free port.
poetry run marimo run app/profiling/dashboard.py --host 0.0.0.0 --port 8124
```

Then access `http://<device-ip>:8124` from your browser, or use `kubectl port-forward pod/<edge-endpoint-pod> 8124:8124` to tunnel through Kubernetes.

### Custom Trace Data Directory

To point the dashboard at a different directory (e.g., trace files copied off a device with `kubectl cp` or `scp`):

```bash
PROFILING_TRACES_DIR=/path/to/traces poetry run marimo run app/profiling/dashboard.py
```

> The dashboard reads and displays whatever JSONL it finds in the configured directory. Only point it at trusted trace data.

### Dashboard Features

- **Summary stats** -- trace count, unique detectors, earliest/latest timestamp in the current filtered view
- **Latency Summary Table** -- per-span p50/p95/p99/mean/min/max statistics
- **Latency Distribution** -- box plots showing duration spread for each span type
- **Latency Over Time** -- p50 and p95 trend lines for key spans in 5-minute buckets
- **Request Throughput** -- bar chart of requests per 5-minute window
- **Trace Waterfall** -- select an individual trace to see a Gantt-style timeline of all spans (showing parallel execution of primary + OODD inference) plus a span-details table with annotations

### Interactive Controls

- **Time range** -- filter to last 15min, 30min, 1h, 2h, 6h, 24h, or all data
- **Detector filter** -- focus on a specific detector. The dropdown is populated from the most recent 24h of trace data and is **not** automatically updated; if new detectors appear while the dashboard is running, reload the browser to see them.
- **Auto-refresh** -- off by default so the dashboard stays put while you investigate. Pick an interval (15s / 30s / 1m / 5m) from the dropdown to enable polling. Does not affect the detector dropdown.

### Troubleshooting

**"No trace data found" callout appears:**

1. Confirm profiling is enabled: check that `ENABLE_PROFILING=true` is set on the edge-endpoint container (Helm: `--set enableProfiling=true`).
2. Confirm the edge-endpoint is serving requests — the trace file is only written on request completion. Send a test request and wait a few seconds.
3. Confirm files exist in the profiling directory:
   ```bash
   ls -la /opt/groundlight/device/edge-profiling/
   ```
   You should see files named `traces_<pid>_<timestamp>.jsonl` being created every 5 minutes.
4. If running with `PROFILING_TRACES_DIR`, double-check the path exists and is readable.

**Dashboard shows old data only:**

Auto-refresh is off by default — click the refresh button in the top row, or pick an interval from the "Auto-refresh" dropdown to enable polling.

**Dashboard shows ModuleNotFoundError for marimo or plotly:**

The optional `profiling` dependency group isn't installed. Run `poetry install --with profiling` from the repo root.

### Editing the Notebook

To add or modify visualizations interactively:

```bash
poetry run marimo edit app/profiling/dashboard.py
```

This opens the full Marimo notebook editor where you can add cells, tweak charts, and experiment. Changes are saved back to `dashboard.py` as plain Python. Marimo creates a `__marimo__/` session-state directory next to the notebook while editing — this is gitignored.
