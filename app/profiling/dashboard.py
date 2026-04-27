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

    # Deterministic color per span name; unknown spans fall back to FALLBACK_COLOR.
    SPAN_COLORS = {
        "request": "#636EFA",
        "post_image_query": "#7F7FFF",
        "get_groundlight_sdk_instance": "#A5A5DD",
        "_get_groundlight_sdk_instance_internal": "#C5C5E8",
        "get_app_state": "#D6D6F0",
        "validate_content_type": "#9EDAE5",
        "validate_image_bytes": "#1F77B4",
        "validate_query_params_for_edge": "#17BECF",
        "active": "#E377C2",
        "detector_config": "#BCBD22",
        "get_detector_metadata": "#EF553B",
        "refresh_detector_metadata_if_needed": "#D62728",
        "inference_is_available": "#00CC96",
        "run_inference": "#3CB371",
        "_submit_primary_inference": "#AB63FA",
        "_submit_oodd_inference": "#FFA15A",
        "parse_inference_response": "#2CA02C",
        "get_inference_result": "#19D3F3",
        "create_iq": "#FECB52",
        "record_activity_for_metrics": "#9467BD",
        "record_confidence_for_metrics": "#8C564B",
        "escalation_cooldown_complete": "#C49C94",
        "safe_escalate_with_queue_write": "#FF6692",
        "write_escalation_to_queue": "#B6E880",
    }
    FALLBACK_COLOR = "#B6B6B6"

    # How many recent traces to offer in the waterfall selector.
    MAX_TRACES_IN_SELECTOR = 50

    return FALLBACK_COLOR, MAX_TRACES_IN_SELECTOR, SPAN_COLORS, mo


@app.cell
def _():
    import os
    import sys

    # Allow running from the repo root — ensure app/ is importable.
    _repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)

    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

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
        make_subplots,
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
    durations_by_span: dict[str, list[float]] = {}
    for _t in traces:
        for _s in _t.get("spans", []):
            _dur = _s.get("duration_ms")
            _name = _s.get("name")
            if _name and _dur is not None and _dur >= 0:
                durations_by_span.setdefault(_name, []).append(_dur)

    _ordered_names = sorted(durations_by_span.keys(), key=span_sort_key)

    if _ordered_names:
        _fig = go.Figure()
        for _name in _ordered_names:
            _fig.add_trace(go.Box(y=durations_by_span[_name], name=_name, boxmean=True))

        _fig.update_layout(
            title="Latency Distribution by Span",
            yaxis_title="Duration (ms)",
            xaxis_title="Span",
            showlegend=True,
            height=450,
        )

        _out = mo.vstack([mo.md("## Latency Distribution"), mo.ui.plotly(_fig)])
    else:
        _out = mo.md("## Latency Distribution\n\n*No span data to plot.*")

    _out
    return (durations_by_span,)


@app.cell
def _(durations_by_span, go, make_subplots, mo, stats):
    # Histograms: one subplot per span, with p50/p95/p99 shown as vertical lines.
    # Each subplot gets its own x-axis so wildly different timescales (e.g. 2ms
    # vs 300ms spans) each remain readable.
    _ordered_names = sorted(durations_by_span.keys(), key=span_sort_key)

    if _ordered_names:
        _cols = 2
        _rows = (len(_ordered_names) + _cols - 1) // _cols
        # vertical_spacing is a fraction of TOTAL plot height between each row pair,
        # so a fixed value compounds with row count. Scale it so total padding
        # (rows-1) * spacing stays bounded, capped so the very-small-grid case still
        # has visible breathing room.
        _vspacing = min(0.08, 0.2 / max(1, _rows - 1))
        _fig = make_subplots(
            rows=_rows,
            cols=_cols,
            subplot_titles=_ordered_names,
            horizontal_spacing=0.12,
            vertical_spacing=_vspacing,
        )

        _percentile_styles = [
            ("p50", "#00CC96"),
            ("p95", "#FFA15A"),
            ("p99", "#EF553B"),
        ]

        for _i, _name in enumerate(_ordered_names):
            _row = (_i // _cols) + 1
            _col = (_i % _cols) + 1

            _fig.add_trace(
                go.Histogram(
                    x=durations_by_span[_name],
                    nbinsx=40,
                    showlegend=False,
                    marker_color="#AAB6FB",
                    hovertemplate="%{x:.1f}ms: %{y} samples<extra></extra>",
                ),
                row=_row,
                col=_col,
            )

            # Overlay percentile lines; label only the first subplot to act as a legend.
            # Any annotation_* kwarg (even with annotation_text=None) triggers plotly's
            # default "new text" label, so we only pass annotation kwargs when we want one.
            _s = stats.get(_name, {})
            _label_this_subplot = _i == 0
            for _label, _color in _percentile_styles:
                _val = _s.get(_label)
                if _val is None:
                    continue
                _vline_kwargs = dict(
                    x=_val,
                    line=dict(color=_color, dash="dash", width=1.5),
                    row=_row,
                    col=_col,
                )
                if _label_this_subplot:
                    _vline_kwargs["annotation_text"] = _label
                    _vline_kwargs["annotation_position"] = "top"
                    _vline_kwargs["annotation_font_color"] = _color
                _fig.add_vline(**_vline_kwargs)

            _fig.update_xaxes(title_text="Duration (ms)", row=_row, col=_col)
            _fig.update_yaxes(title_text="Count", row=_row, col=_col)

        _fig.update_layout(
            height=320 * _rows,
            showlegend=False,
            margin=dict(t=50, b=40),
        )

        _out = mo.vstack(
            [
                mo.md("### Histograms _(p50 green, p95 orange, p99 red)_"),
                mo.ui.plotly(_fig),
            ]
        )
    else:
        _out = mo.md("### Histograms\n\n*No span data to plot.*")

    _out


@app.cell
def _(FALLBACK_COLOR, SPAN_COLORS, go, mo, traces):
    # Scatterplot of every span's duration over time, colored by span name.
    # Each trace contributes one point per span, so cache hits vs misses and
    # individual outliers per span type are directly visible. Click a legend
    # entry to toggle that span on/off.
    _points_by_span: dict[str, list[tuple[str, float, str]]] = {}
    for _t in traces:
        _wall = _t.get("start_wall_time_iso", "")
        _tid = _t.get("trace_id", "")
        if not _wall:
            continue
        for _s in _t.get("spans", []):
            _name = _s.get("name")
            _dur = _s.get("duration_ms")
            if _name and _dur is not None and _dur >= 0:
                _points_by_span.setdefault(_name, []).append((_wall, _dur, _tid))

    _ordered_names = sorted(_points_by_span.keys(), key=span_sort_key)

    if _ordered_names:
        _fig = go.Figure()
        for _name in _ordered_names:
            _points = _points_by_span[_name]
            _fig.add_trace(
                go.Scatter(
                    x=[_p[0] for _p in _points],
                    y=[_p[1] for _p in _points],
                    mode="markers",
                    name=_name,
                    marker=dict(
                        size=5,
                        opacity=0.6,
                        color=SPAN_COLORS.get(_name, FALLBACK_COLOR),
                    ),
                    customdata=[_p[2] for _p in _points],
                    hovertemplate=(
                        f"<b>{_name}</b><br>"
                        "Time: %{x}<br>"
                        "Duration: %{y:.1f}ms<br>"
                        "Trace: %{customdata}<extra></extra>"
                    ),
                )
            )

        _fig.update_layout(
            xaxis_title="Time",
            yaxis_title="Span duration (ms)",
            height=500,
            margin=dict(t=20, b=80),
            legend=dict(orientation="h", yanchor="top", y=-0.25, xanchor="center", x=0.5),
            hovermode="closest",
        )

        _out = mo.vstack(
            [
                mo.md("## Latency Over Time _(one point per span, colored by span)_"),
                mo.ui.plotly(_fig),
            ]
        )
    else:
        _out = mo.md("## Latency Over Time\n\n*Not enough span data to plot.*")

    _out


@app.cell
def _(go, mo, traces):
    # Individual-trace scatterplot: x=wall time, y=full-request duration, one point per trace.
    # Grouped by detector so each detector gets its own color and can be toggled in the legend.
    _by_detector: dict[str, list[tuple[str, float, str]]] = {}
    for _t in traces:
        _dur = trace_duration_ms(_t)
        _ts = _t.get("start_wall_time_iso", "")
        _det = _t.get("detector_id") or "unknown"
        _tid = _t.get("trace_id", "")
        if _dur > 0 and _ts:
            _by_detector.setdefault(_det, []).append((_ts, _dur, _tid))

    if _by_detector:
        _fig = go.Figure()
        for _det in sorted(_by_detector.keys()):
            _points = _by_detector[_det]
            _fig.add_trace(
                go.Scatter(
                    x=[_p[0] for _p in _points],
                    y=[_p[1] for _p in _points],
                    mode="markers",
                    name=_det,
                    marker=dict(size=6, opacity=0.7),
                    customdata=[_p[2] for _p in _points],
                    hovertemplate=(
                        f"<b>{_det}</b><br>"
                        "Time: %{x}<br>"
                        "Duration: %{y:.1f}ms<br>"
                        "Trace: %{customdata}<extra></extra>"
                    ),
                )
            )

        _fig.update_layout(
            xaxis_title="Time",
            yaxis_title="Request duration (ms)",
            height=500,
            margin=dict(t=20, b=80),
            legend=dict(orientation="h", yanchor="top", y=-0.25, xanchor="center", x=0.5),
            hovermode="closest",
        )

        _out = mo.vstack(
            [
                mo.md("## Request Duration Scatter _(one point per trace)_"),
                mo.ui.plotly(_fig),
            ]
        )
    else:
        _out = mo.md("## Request Duration Scatter\n\n*No request data to plot.*")

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
                customdata=[[start_ms + dur, dur]],
                hovertemplate=(
                    "Start: %{base:.1f}ms<br>"
                    "End: %{customdata[0]:.1f}ms<br>"
                    "Duration: %{customdata[1]:.1f}ms<extra></extra>"
                ),
                showlegend=False,
            )
        )

    fig.update_layout(
        xaxis_title="Time from request start (ms)",
        height=max(200, 40 * len(bars) + 100),
        barmode="overlay",
        yaxis=dict(autorange="reversed"),
        margin=dict(t=20, b=40),
    )

    span_table = []
    for s in spans:
        annotations = s.get("annotations") or {}
        annotation_str = ", ".join(f"{k}={v}" for k, v in sorted(annotations.items())) if annotations else ""
        start_ms = (s.get("start_time_ns", 0) - root_start) / 1_000_000
        dur = s.get("duration_ms", 0) or 0
        span_table.append(
            {
                "Span": s.get("name", "unknown"),
                "Start (ms)": round(start_ms, 2),
                "End (ms)": round(start_ms + dur, 2),
                "Duration (ms)": round(dur, 2),
                "Span ID": s.get("span_id", ""),
                "Parent": s.get("parent_span_id") or "(root)",
                "Annotations": annotation_str,
            }
        )

    trace_id = detail.get("trace_id", "")
    detector_id = detail.get("detector_id", "")
    return mo.vstack(
        [
            mo.md(f"**Detector ID:** `{detector_id}`  \n**Trace ID:** `{trace_id}`"),
            mo.ui.plotly(fig),
            mo.ui.table(span_table, selection=None, label="Span details"),
        ]
    )


if __name__ == "__main__":
    app.run()
