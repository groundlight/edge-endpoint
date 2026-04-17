import marimo

__generated_with = "0.23.1"
app = marimo.App(width="medium", app_title="Edge Endpoint Profiling Dashboard")


@app.function
def span_sort_key(name: str) -> tuple[int, str]:
    """Sort key that puts the 'request' root span first, then alphabetical."""
    return (0 if name == "request" else 1, name)


@app.cell
def _():
    import marimo as mo

    # Key spans driving the time-series chart; also canonical ordering hint.
    KEY_SPANS = [
        "request",
        "_submit_primary_inference",
        "_submit_oodd_inference",
        "get_inference_result",
    ]

    # Deterministic color per span name; unknown spans fall back to FALLBACK_COLOR.
    SPAN_COLORS = {
        "request": "#636EFA",
        "get_detector_metadata": "#EF553B",
        "inference_is_available": "#00CC96",
        "_submit_primary_inference": "#AB63FA",
        "_submit_oodd_inference": "#FFA15A",
        "get_inference_result": "#19D3F3",
        "safe_escalate_with_queue_write": "#FF6692",
        "write_escalation_to_queue": "#B6E880",
    }
    FALLBACK_COLOR = "#B6B6B6"

    # How many recent traces to offer in the waterfall selector.
    MAX_TRACES_IN_SELECTOR = 50

    return FALLBACK_COLOR, KEY_SPANS, MAX_TRACES_IN_SELECTOR, SPAN_COLORS, mo


@app.cell
def _():
    import os
    import sys

    # Allow running from the repo root — ensure app/ is importable.
    _repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)

    import plotly.graph_objects as go

    from app.profiling.data_loader import (
        compute_span_stats,
        compute_time_series,
        get_detector_ids,
        get_trace_detail,
        load_traces,
    )
    from app.profiling.manager import PROFILING_DIR

    return (
        PROFILING_DIR,
        compute_span_stats,
        compute_time_series,
        get_detector_ids,
        get_trace_detail,
        go,
        load_traces,
    )


@app.cell
def _(mo):
    mo.md(
        """
        # Edge Endpoint Profiling Dashboard

        Visualize request-level trace data from the edge inference pipeline.
        Traces are read from JSONL files written by the profiling middleware.
        """
    )


@app.cell
def _(PROFILING_DIR, mo):
    import os as _os

    traces_dir = _os.environ.get("PROFILING_TRACES_DIR", PROFILING_DIR)

    # Auto-refresh is opt-in (no default_interval) so the dashboard stays put
    # while you investigate a trace. Pick an interval from the dropdown to enable.
    refresh = mo.ui.refresh(options=["15s", "30s", "1m", "5m"], label="Auto-refresh")

    _time_options = {
        "Last 15 min": 15,
        "Last 30 min": 30,
        "Last 1 hour": 60,
        "Last 2 hours": 120,
        "Last 6 hours": 360,
        "Last 24 hours": 1440,
        "All": 0,
    }
    time_range = mo.ui.dropdown(
        options=_time_options,
        value="Last 1 hour",
        label="Time range",
    )

    return refresh, time_range, traces_dir


@app.cell
def _(get_detector_ids, load_traces, mo, traces_dir):
    # Populate the detector dropdown from the most recent 24h of traces.
    # Deliberately does NOT depend on `refresh` — the dropdown is rebuilt only
    # when the notebook is reloaded. This keeps the user's detector selection
    # stable across auto-refresh ticks. New detectors that appear mid-session
    # require a browser reload to show up in the dropdown.
    _recent_traces = load_traces(traces_dir, since_minutes=1440)
    _detector_options = {"All detectors": ""}
    for _d in get_detector_ids(_recent_traces):
        _detector_options[_d] = _d

    detector_filter = mo.ui.dropdown(
        options=_detector_options,
        value="All detectors",
        label="Detector",
    )
    return (detector_filter,)


@app.cell
def _(detector_filter, mo, refresh, time_range):
    mo.hstack([time_range, detector_filter, refresh], justify="start", gap=1)


@app.cell
def _(detector_filter, get_detector_ids, load_traces, mo, refresh, time_range, traces_dir):
    # Reactive: re-runs when controls change or auto-refresh fires.
    _ = refresh

    _since_val = time_range.value  # mapped int from dict options; 0 means "all"
    _since = int(_since_val) if _since_val else None
    _det = detector_filter.value or None
    traces = load_traces(traces_dir, since_minutes=_since, detector_id=_det)

    if not traces:
        _summary = mo.callout(
            "No trace data found in the selected range. Make sure profiling is enabled "
            "(`ENABLE_PROFILING=true`) and that the edge-endpoint is handling requests.",
            kind="warn",
        )
    else:
        _count = len(traces)
        _times = [t.get("start_wall_time_iso", "") for t in traces if t.get("start_wall_time_iso")]
        _earliest = min(_times) if _times else "N/A"
        _latest = max(_times) if _times else "N/A"
        # Match get_detector_ids semantics: exclude empty and "unknown".
        _detectors = len(get_detector_ids(traces))

        _summary = mo.hstack(
            [
                mo.stat(label="Traces", value=f"{_count:,}"),
                mo.stat(label="Detectors", value=str(_detectors)),
                mo.stat(label="Earliest", value=_earliest[:19].replace("T", " ")),
                mo.stat(label="Latest", value=_latest[:19].replace("T", " ")),
            ],
            justify="start",
            gap=1,
        )

    _summary
    return (traces,)


@app.cell
def _(compute_span_stats, mo, traces):
    stats = compute_span_stats(traces)

    _table_data = []
    for _name in sorted(stats.keys(), key=span_sort_key):
        _s = stats[_name]
        _table_data.append(
            {
                "Span": _name,
                "Count": _s["count"],
                "p50 (ms)": _s["p50"],
                "p95 (ms)": _s["p95"],
                "p99 (ms)": _s["p99"],
                "Mean (ms)": _s["mean"],
                "Min (ms)": _s["min"],
                "Max (ms)": _s["max"],
            }
        )

    if _table_data:
        _out = mo.vstack(
            [
                mo.md("## Latency Summary by Span"),
                mo.ui.table(_table_data, selection=None, label="Per-span latency statistics"),
            ]
        )
    else:
        _out = mo.md("## Latency Summary by Span\n\n*No spans to display.*")

    _out
    return (stats,)


@app.cell
def _(go, mo, traces):
    _durations_by_span: dict[str, list[float]] = {}
    for _t in traces:
        for _s in _t.get("spans", []):
            _dur = _s.get("duration_ms")
            _name = _s.get("name")
            if _name and _dur is not None and _dur >= 0:
                _durations_by_span.setdefault(_name, []).append(_dur)

    _ordered_names = sorted(_durations_by_span.keys(), key=span_sort_key)

    if _ordered_names:
        _fig = go.Figure()
        for _name in _ordered_names:
            _fig.add_trace(go.Box(y=_durations_by_span[_name], name=_name, boxmean=True))

        _fig.update_layout(
            title="Latency Distribution by Span",
            yaxis_title="Duration (ms)",
            xaxis_title="Span",
            showlegend=False,
            height=450,
        )

        _out = mo.vstack([mo.md("## Latency Distribution"), mo.ui.plotly(_fig)])
    else:
        _out = mo.md("## Latency Distribution\n\n*No span data to plot.*")

    _out


@app.cell
def _(KEY_SPANS, compute_time_series, go, mo, traces):
    _existing_spans = {_s.get("name") for _t in traces for _s in _t.get("spans", []) if _s.get("name")}
    _spans_to_plot = [s for s in KEY_SPANS if s in _existing_spans]

    if _spans_to_plot:
        _fig = go.Figure()
        for _name in _spans_to_plot:
            _series = compute_time_series(traces, _name, bucket_minutes=5)
            if _series:
                _times = [e["time"] for e in _series]
                _fig.add_trace(
                    go.Scatter(
                        x=_times,
                        y=[e["p50"] for e in _series],
                        mode="lines+markers",
                        name=f"{_name} p50",
                    )
                )
                _fig.add_trace(
                    go.Scatter(
                        x=_times,
                        y=[e["p95"] for e in _series],
                        mode="lines",
                        name=f"{_name} p95",
                        line=dict(dash="dash"),
                    )
                )

        _fig.update_layout(
            xaxis_title="Time",
            yaxis_title="Duration (ms)",
            height=500,
            margin=dict(t=20, b=80),
            legend=dict(orientation="h", yanchor="top", y=-0.25, xanchor="center", x=0.5),
        )

        _out = mo.vstack(
            [
                mo.md("## Latency Over Time _(p50 solid, p95 dashed)_"),
                mo.ui.plotly(_fig),
            ]
        )
    else:
        _out = mo.md("## Latency Over Time\n\n*Not enough span data to plot time series.*")

    _out


@app.cell
def _(SPAN_COLORS, compute_time_series, go, mo, traces):
    _series = compute_time_series(traces, "request", bucket_minutes=5)
    if _series:
        _fig = go.Figure()
        _fig.add_trace(
            go.Bar(
                x=[e["time"] for e in _series],
                y=[e["count"] for e in _series],
                marker_color=SPAN_COLORS["request"],
            )
        )
        _fig.update_layout(
            title="Request Throughput",
            xaxis_title="Time",
            yaxis_title="Requests per 5-min Bucket",
            height=350,
        )
        _out = mo.vstack([mo.md("## Throughput"), mo.ui.plotly(_fig)])
    else:
        _out = mo.md("## Throughput\n\n*No data.*")

    _out


@app.function
def trace_duration_ms(trace: dict) -> float:
    """Return the root ('request') span's duration for a trace, or 0.0 if not present."""
    for span in trace.get("spans", []):
        if span.get("name") == "request":
            dur = span.get("duration_ms")
            if dur is not None and dur >= 0:
                return dur
    return 0.0


@app.cell
def _(mo, traces):
    # Collect all span names present in the current trace set to populate the filter.
    _all_span_names = set()
    for _t in traces:
        for _s in _t.get("spans", []):
            _n = _s.get("name")
            if _n:
                _all_span_names.add(_n)

    _span_filter_options = {"Any span": ""}
    for _n in sorted(_all_span_names, key=span_sort_key):
        _span_filter_options[_n] = _n

    span_filter = mo.ui.dropdown(
        options=_span_filter_options,
        value="Any span",
        label="Containing span",
    )

    sort_order = mo.ui.dropdown(
        options=["Most recent", "Longest", "Shortest"],
        value="Most recent",
        label="Sort by",
    )
    return span_filter, sort_order


@app.cell
def _(MAX_TRACES_IN_SELECTOR, mo, sort_order, span_filter, traces):
    # Apply the span filter, then sort according to the selected order.
    _required_span = span_filter.value
    if _required_span:
        _matching = [_t for _t in traces if any(_s.get("name") == _required_span for _s in _t.get("spans", []))]
    else:
        _matching = traces

    if sort_order.value == "Longest":
        _sorted = sorted(_matching, key=trace_duration_ms, reverse=True)
    elif sort_order.value == "Shortest":
        _sorted = sorted(_matching, key=trace_duration_ms)
    else:  # "Most recent"
        _sorted = sorted(_matching, key=lambda t: t.get("start_wall_time_iso", ""), reverse=True)

    _top = _sorted[:MAX_TRACES_IN_SELECTOR]

    _trace_options = {"(none)": ""}
    for _t in _top:
        _ts = _t.get("start_wall_time_iso", "")[:19]
        _det = _t.get("detector_id", "?")
        _tid = _t.get("trace_id", "")
        _dur = trace_duration_ms(_t)
        _label = f"{_ts} | {_det} | {_dur:>6.1f}ms | {_tid[:12]}"
        _trace_options[_label] = _tid

    trace_selector = mo.ui.dropdown(options=_trace_options, value="(none)", label="Select trace")

    _total = len(_matching)
    _shown = len(_top)
    _count_note = (
        f"Showing {_shown} of {_total} matching traces."
        if _shown < _total
        else f"Showing all {_total} matching traces."
    )

    mo.vstack(
        [
            mo.md("## Trace Waterfall"),
            mo.md(
                f"Filter by a span to find specific traces (e.g. `safe_escalate_with_queue_write` for escalations), "
                f"sort to find outliers, then select one to see a Gantt-style timeline. "
                f"{_count_note}"
            ),
            mo.hstack([span_filter, sort_order, trace_selector], justify="start", gap=1),
        ]
    )
    return (trace_selector,)


@app.cell
def _(FALLBACK_COLOR, SPAN_COLORS, get_trace_detail, go, mo, trace_selector, traces):
    if not trace_selector.value:
        _output = mo.md("*Select a trace above to view its waterfall.*")
    else:
        _detail = get_trace_detail(traces, trace_selector.value)
        if not _detail:
            _output = mo.md("*Trace not found.*")
        else:
            _spans = _detail.get("spans", [])
            if not _spans:
                _output = mo.md("*Trace has no spans.*")
            else:
                _output = build_waterfall(_detail, _spans, go, mo, SPAN_COLORS, FALLBACK_COLOR)

    _output


@app.function
def build_waterfall(detail, spans, go, mo, span_colors, fallback_color):
    """Build a Gantt-style waterfall figure and span table for a single trace."""
    root_start = min(s.get("start_time_ns", 0) for s in spans)

    bars = []
    for s in spans:
        dur = s.get("duration_ms", 0)
        if dur is None or dur < 0:
            continue
        name = s.get("name", "unknown")
        start_ms = (s.get("start_time_ns", 0) - root_start) / 1_000_000
        bars.append((name, start_ms, dur))

    fig = go.Figure()
    for name, start_ms, dur in bars:
        fig.add_trace(
            go.Bar(
                y=[name],
                x=[dur],
                base=[start_ms],
                orientation="h",
                marker_color=span_colors.get(name, fallback_color),
                name=name,
                hovertemplate="Start: %{base:.1f}ms<br>Duration: %{x:.1f}ms<extra></extra>",
                showlegend=False,
            )
        )

    fig.update_layout(
        title=f"Trace {detail.get('trace_id', '')[:16]} | {detail.get('detector_id', '?')}",
        xaxis_title="Time from request start (ms)",
        height=max(200, 40 * len(bars) + 100),
        barmode="overlay",
        yaxis=dict(autorange="reversed"),
    )

    span_table = []
    for s in spans:
        annotations = s.get("annotations") or {}
        annotation_str = ", ".join(f"{k}={v}" for k, v in sorted(annotations.items())) if annotations else ""
        parent = s.get("parent_span_id")
        span_table.append(
            {
                "Span": s.get("name", "unknown"),
                "Start (ms)": round((s.get("start_time_ns", 0) - root_start) / 1_000_000, 2),
                "Duration (ms)": round(s.get("duration_ms", 0), 2),
                "Parent": parent[:8] if parent else "(root)",
                "Annotations": annotation_str,
            }
        )

    return mo.vstack(
        [
            mo.ui.plotly(fig),
            mo.ui.table(span_table, selection=None, label="Span details"),
        ]
    )


if __name__ == "__main__":
    app.run()
