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
        "validate_image_bytes": "#1F77B4",
        "validate_query_params_for_edge": "#17BECF",
        "active": "#E377C2",
        "detector_config": "#BCBD22",
        "get_detector_metadata": "#EF553B",
        "inference_is_available": "#00CC96",
        "_submit_primary_inference": "#AB63FA",
        "_submit_oodd_inference": "#FFA15A",
        "parse_inference_response": "#2CA02C",
        "get_inference_result": "#19D3F3",
        "create_iq": "#FECB52",
        "record_activity_for_metrics": "#9467BD",
        "record_confidence_for_metrics": "#8C564B",
        "safe_escalate_with_queue_write": "#FF6692",
        "write_escalation_to_queue": "#B6E880",
    }
    FALLBACK_COLOR = "#B6B6B6"

    # Qualitative palette used to auto-color spans that aren't in SPAN_COLORS.
    AUTO_PALETTE = [
        "#636EFA",
        "#EF553B",
        "#00CC96",
        "#AB63FA",
        "#FFA15A",
        "#19D3F3",
        "#FF6692",
        "#B6E880",
        "#FF97FF",
        "#FECB52",
        "#1F77B4",
        "#FF7F0E",
        "#2CA02C",
        "#D62728",
        "#9467BD",
        "#8C564B",
        "#E377C2",
        "#7F7F7F",
        "#BCBD22",
        "#17BECF",
    ]

    # How many recent traces to offer in the waterfall selector.
    MAX_TRACES_IN_SELECTOR = 50

    return AUTO_PALETTE, FALLBACK_COLOR, MAX_TRACES_IN_SELECTOR, SPAN_COLORS, mo


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
        merge_traces_by_id,
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
        merge_traces_by_id,
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
def _(detector_filter, get_detector_ids, load_traces, merge_traces_by_id, mo, refresh, time_range, traces_dir):
    # Reactive: re-runs when controls change or auto-refresh fires.
    _ = refresh

    _since_val = time_range.value  # mapped int from dict options; 0 means "all"
    _since = int(_since_val) if _since_val else None
    _det = detector_filter.value or None
    # Load all records (no detector filter at load time) so that cross-process
    # records sharing a trace_id can be merged. The inference-side records carry
    # an empty detector_id and would otherwise be dropped before merge. Apply
    # the detector filter to the merged trace set.
    traces = merge_traces_by_id(load_traces(traces_dir, since_minutes=_since))
    if _det:
        traces = [t for t in traces if t.get("detector_id") == _det]

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

    _ordered_names = sorted(
        durations_by_span.keys(),
        key=lambda n: sum(durations_by_span[n]) / len(durations_by_span[n]),
        reverse=True,
    )

    if _ordered_names:
        _fig = go.Figure()
        for _name in _ordered_names:
            _fig.add_trace(go.Box(y=durations_by_span[_name], name=_name, boxmean=True))

        _fig.update_layout(
            title="Latency Distribution by Span",
            yaxis_title="Duration (ms)",
            xaxis_title="Span",
            xaxis=dict(categoryorder="array", categoryarray=_ordered_names),
            showlegend=True,
            height=450,
        )

        _out = mo.vstack([mo.md("## Latency Distribution"), mo.ui.plotly(_fig)])
    else:
        _out = mo.md("## Latency Distribution\n\n*No span data to plot.*")

    _out
    return (durations_by_span,)


@app.cell
def _(durations_by_span, mo):
    # Dropdown to pick a single span for the histogram below. Default to "request"
    # so the full per-request distribution is what you see first.
    _ordered_names = sorted(durations_by_span.keys(), key=span_sort_key)
    if _ordered_names:
        _options = {_n: _n for _n in _ordered_names}
        _default = "request" if "request" in _options else _ordered_names[0]
        histogram_span = mo.ui.dropdown(options=_options, value=_default, label="Histogram span")
    else:
        histogram_span = mo.ui.dropdown(options={}, label="Histogram span")
    return (histogram_span,)


@app.cell
def _(durations_by_span, go, histogram_span, mo, stats):
    # Render a single histogram for the selected span, with p50/p95/p99 vlines.
    _name = histogram_span.value
    _samples = durations_by_span.get(_name) if _name else None

    if not _samples:
        _out = mo.vstack(
            [
                mo.md("### Histograms _(p50 green, p95 orange, p99 red)_"),
                histogram_span,
                mo.md("*No span data to plot.*"),
            ]
        )
    else:
        _fig = go.Figure()
        _fig.add_trace(
            go.Histogram(
                x=_samples,
                nbinsx=40,
                showlegend=False,
                marker_color="#AAB6FB",
                hovertemplate="%{x:.1f}ms: %{y} samples<extra></extra>",
            )
        )

        _percentile_styles = [
            ("p50", "#00CC96"),
            ("p95", "#FFA15A"),
            ("p99", "#EF553B"),
        ]
        _s = stats.get(_name, {})
        for _label, _color in _percentile_styles:
            _val = _s.get(_label)
            if _val is None:
                continue
            _fig.add_vline(
                x=_val,
                line=dict(color=_color, dash="dash", width=1.5),
                annotation_text=_label,
                annotation_position="top",
                annotation_font_color=_color,
            )

        _fig.update_layout(
            xaxis_title="Duration (ms)",
            yaxis_title="Count",
            height=400,
            showlegend=False,
            margin=dict(t=40, b=40),
            title=_name,
        )

        _out = mo.vstack(
            [
                mo.md("### Histograms _(p50 green, p95 orange, p99 red)_"),
                histogram_span,
                mo.ui.plotly(_fig),
            ]
        )

    _out


@app.cell
def _(mo, traces):
    _all_span_names = set()
    for _t in traces:
        for _s in _t.get("spans", []):
            _n = _s.get("name")
            if _n:
                _all_span_names.add(_n)
    _ordered = sorted(_all_span_names, key=span_sort_key)

    _defaults = [_n for _n in ("_submit_primary_inference", "_submit_oodd_inference") if _n in _all_span_names]

    latency_over_time_spans = mo.ui.multiselect(
        options=_ordered,
        value=_defaults,
        label="Spans to plot",
    )
    latency_over_time_spans
    return (latency_over_time_spans,)


@app.cell
def _(AUTO_PALETTE, SPAN_COLORS, go, latency_over_time_spans, mo, traces):
    # Scatterplot of selected spans' durations over time, colored by span name.
    # Only spans chosen in the multiselect are embedded in the plot payload —
    # plotting every span can exceed marimo's output size limit.
    _selected = set(latency_over_time_spans.value or [])
    _points_by_span: dict[str, list[tuple[str, float, str]]] = {}
    for _t in traces:
        _wall = _t.get("start_wall_time_iso", "")
        _tid = _t.get("trace_id", "")
        if not _wall:
            continue
        for _s in _t.get("spans", []):
            _name = _s.get("name")
            if _name not in _selected:
                continue
            _dur = _s.get("duration_ms")
            if _dur is not None and _dur >= 0:
                _points_by_span.setdefault(_name, []).append((_wall, _dur, _tid))

    _ordered_names = sorted(_points_by_span.keys(), key=span_sort_key)

    # Assign a distinct color to every plotted span: use the explicit SPAN_COLORS
    # mapping when available, otherwise cycle through AUTO_PALETTE so spans
    # without a predefined color still look distinct.
    _unknowns = [_n for _n in _ordered_names if _n not in SPAN_COLORS]
    _auto_colors = {_n: AUTO_PALETTE[_i % len(AUTO_PALETTE)] for _i, _n in enumerate(_unknowns)}

    if _ordered_names:
        _fig = go.Figure()
        for _name in _ordered_names:
            _points = _points_by_span[_name]
            _fig.add_trace(
                go.Scattergl(
                    x=[_p[0] for _p in _points],
                    y=[_p[1] for _p in _points],
                    mode="markers",
                    name=_name,
                    marker=dict(
                        size=5,
                        opacity=0.6,
                        color=SPAN_COLORS.get(_name, _auto_colors.get(_name)),
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
        _out = mo.md("## Latency Over Time\n\n*Select at least one span to plot.*")

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
    """Build a Gantt-style waterfall figure and span table for a single trace.

    Spans are ordered by depth-first pre-order traversal of the parent/child tree
    so children sit directly under their parent, and y-axis labels are indented by
    depth. Each span gets its own row (indexed by an integer y-position) so spans
    that share a name — e.g. an inference-server span emitted under both the
    primary and OODD wrappers — don't collide on the same row.
    """
    root_start = min(s.get("start_time_ns", 0) for s in spans)

    span_by_id = {s.get("span_id"): s for s in spans if s.get("span_id")}
    children_by_parent: dict = {}
    for s in spans:
        pid = s.get("parent_span_id")
        if pid not in span_by_id:
            pid = None  # treat orphans (parent missing from merged set) as roots
        children_by_parent.setdefault(pid, []).append(s)
    for kids in children_by_parent.values():
        kids.sort(key=lambda s: s.get("start_time_ns", 0))

    ordered: list = []  # list of (span, depth) in DFS pre-order
    # Iterative DFS: marimo rewrites function names with cell-local prefixes,
    # which breaks self-recursion inside nested helpers.
    stack: list = [(s, 0) for s in reversed(children_by_parent.get(None, []))]
    while stack:
        node, depth = stack.pop()
        ordered.append((node, depth))
        children = children_by_parent.get(node.get("span_id"), [])
        for child in reversed(children):
            stack.append((child, depth + 1))

    # Track placed spans by object identity rather than span_id so that spans
    # without a span_id don't all collapse onto a single "already placed"
    # sentinel and get silently dropped by the orphan-fallback loop.
    placed = {id(s) for s, _ in ordered}
    for s in spans:
        if id(s) not in placed:
            ordered.append((s, 0))

    # Tint every descendant of a primary/OODD inference wrapper with the wrapper's
    # color so it's visually obvious which branch a given inference-pod span ran
    # under. Walks the subtree under each wrapper span using the same iterative DFS.
    inherited_color: dict = {}
    for s in spans:
        if s.get("name") in ("_submit_primary_inference", "_submit_oodd_inference"):
            wrapper_color = span_colors.get(s.get("name"), fallback_color)
            sub_stack: list = [s.get("span_id")]
            while sub_stack:
                pid = sub_stack.pop()
                for child in children_by_parent.get(pid, []):
                    cid = child.get("span_id")
                    if cid is not None and cid not in inherited_color:
                        inherited_color[cid] = wrapper_color
                        sub_stack.append(cid)

    fig = go.Figure()
    tickvals: list = []
    ticktext: list = []
    for idx, (s, depth) in enumerate(ordered):
        dur = s.get("duration_ms", 0)
        if dur is None or dur < 0:
            continue
        name = s.get("name", "unknown")
        start_ms = (s.get("start_time_ns", 0) - root_start) / 1_000_000
        label = ("    " * depth) + name
        tickvals.append(idx)
        ticktext.append(label)
        bar_color = inherited_color.get(s.get("span_id")) or span_colors.get(name, fallback_color)
        fig.add_trace(
            go.Bar(
                y=[idx],
                x=[dur],
                base=[start_ms],
                orientation="h",
                marker_color=bar_color,
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
        height=max(200, 28 * len(ordered) + 100),
        barmode="overlay",
        yaxis=dict(
            tickmode="array",
            tickvals=tickvals,
            ticktext=ticktext,
            autorange="reversed",
        ),
        margin=dict(t=20, b=40, l=320),
    )

    span_table = []
    for s, depth in ordered:
        annotations = s.get("annotations") or {}
        annotation_str = ", ".join(f"{k}={v}" for k, v in sorted(annotations.items())) if annotations else ""
        start_ms = (s.get("start_time_ns", 0) - root_start) / 1_000_000
        dur = s.get("duration_ms", 0) or 0
        span_table.append(
            {
                "Span": ("    " * depth) + s.get("name", "unknown"),
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
