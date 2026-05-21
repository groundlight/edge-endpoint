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

## Profiling Dashboard

A [Marimo](https://marimo.io/) notebook provides interactive visualization of trace data. Marimo and plotly live in an **optional** `profiling` dependency group, so they are **not** installed by default — you'll need to install them wherever you launch the dashboard.

### Running on an Edge Device

SSH into the device with a local port forward so you can open the dashboard in your laptop's browser:

```bash
ssh -L 2718:localhost:2718 user@<device>
```

Then on the remote machine, install the dashboard dependencies and launch:

```bash
uv sync --no-install-project --no-default-groups --group profiling
uv run marimo run app/profiling/dashboard.py
```

Open `http://localhost:2718` in your laptop's browser. Marimo binds to localhost on the device by default; the SSH tunnel handles the rest. Stop with `Ctrl+C` on the remote; close the SSH session to tear the tunnel down.

The dashboard is **read-only** in `run` mode — to edit cells, use `marimo edit` (see [Editing the Notebook](#editing-the-notebook) below).

### Running on a Laptop

A secondary workflow for offline analysis of trace files copied off a device.

1. Copy the JSONL trace files to your laptop with `kubectl cp` or `scp`, e.g.:
   ```bash
   kubectl cp <pod>:/opt/groundlight/device/edge-profiling/ ./traces/
   ```
2. Install the optional dashboard dependencies in your local repo checkout:
   ```bash
   uv sync --no-install-project --no-default-groups --group profiling
   ```
3. Run the dashboard, pointing it at the copied trace directory:
   ```bash
   PROFILING_TRACES_DIR=./traces uv run marimo run app/profiling/dashboard.py
   ```

Marimo starts a web server on port 2718 (or the next open port) and prints the URL.

> The dashboard reads and displays whatever JSONL it finds in the configured directory. Only point it at trusted trace data.

### Dashboard Features

- **Summary stats** -- trace count, unique detectors, earliest/latest timestamp in the current filtered view
- **Latency Summary Table** -- per-span p50/p95/p99/mean/min/max statistics
- **Latency Distribution** -- box plots showing duration spread for each span type (click a legend entry to hide that span), followed by per-span histograms with p50/p95/p99 markers for finer-grained shape inspection
- **Latency Over Time** -- scatterplot with one point per span per trace, colored by span name; click a legend entry to toggle that span. Reveals per-span outliers and bimodal patterns (e.g., cache hit vs miss) that bucketed aggregates would smooth over.
- **Request Duration Scatter** -- one point per trace (x = wall time, y = full-request duration) grouped by detector for color; hover shows the trace ID so you can look up slow outliers in the waterfall selector below
- **Request Throughput** -- bar chart of requests per 5-minute window
- **Trace Waterfall** -- select an individual trace to see a Gantt-style timeline of all spans (showing parallel execution of primary + OODD inference). The full `Detector ID` and `Trace ID` appear above the chart in copyable code blocks; hover over any bar for start, end, and duration in ms. The span-details table below includes the full `Span ID` and `Parent` IDs (for correlating with logs) plus any annotations set on the span.

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

The optional `profiling` dependency group isn't installed. Run `uv sync --no-install-project --no-default-groups --group profiling` from the repo root.

### Editing the Notebook

To add or modify visualizations interactively:

```bash
uv run marimo edit app/profiling/dashboard.py
```

This opens the full Marimo notebook editor where you can add cells, tweak charts, and experiment. Changes are saved back to `dashboard.py` as plain Python. Marimo creates a `__marimo__/` session-state directory next to the notebook while editing — this is gitignored.
