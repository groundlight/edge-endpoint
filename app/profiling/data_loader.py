"""Load and aggregate profiling trace data from JSONL files on disk.

This module is used by the Marimo dashboard notebook and can also be used
independently for CLI analysis or testing.
"""

import json
import logging
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.profiling.manager import PROFILING_DIR

logger = logging.getLogger(__name__)


def load_traces(
    traces_dir: str = PROFILING_DIR,
    since_minutes: int | None = None,
    detector_id: str | None = None,
) -> list[dict]:
    """Load traces from JSONL files, optionally filtered by time and detector.

    Args:
        traces_dir: Directory containing trace JSONL files.
        since_minutes: If set, only include traces from the last N minutes.
        detector_id: If set, only include traces for this detector.

    Returns:
        List of trace dicts (as written by Trace.to_dict()).
    """
    traces_path = Path(traces_dir)
    if not traces_path.is_dir():
        return []

    cutoff_mtime = None
    cutoff_time = None
    if since_minutes is not None:
        cutoff_mtime = time.time() - (since_minutes * 60)
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)

    traces = []
    for filepath in sorted(traces_path.glob("traces_*.jsonl")):
        if cutoff_mtime is not None:
            try:
                if filepath.stat().st_mtime < cutoff_mtime:
                    continue
            except OSError:
                continue

        try:
            with open(filepath) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        trace = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning(f"Skipping malformed JSON line in {filepath}")
                        continue

                    if cutoff_time is not None:
                        trace_time = _parse_iso_time(trace.get("start_wall_time_iso", ""))
                        if trace_time is None:
                            # Unparseable or naive timestamp — skip rather than crash.
                            continue
                        if trace_time < cutoff_time:
                            continue

                    if detector_id is not None and trace.get("detector_id") != detector_id:
                        continue

                    traces.append(trace)
        except OSError:
            logger.warning(f"Failed to read trace file {filepath}")

    return traces


def compute_span_stats(traces: list[dict]) -> dict[str, dict]:
    """Compute latency statistics grouped by span name.

    Returns:
        Dict mapping span name to {"p50", "p95", "p99", "mean", "min", "max", "count"}.

    Percentiles use `method='inclusive'`, which clamps values within the observed
    range — avoids the surprising case where p99 exceeds the observed max.
    """
    durations_by_name: dict[str, list[float]] = {}
    for trace in traces:
        for span in trace.get("spans", []):
            duration = span.get("duration_ms")
            if duration is not None and duration >= 0:
                name = span.get("name", "unknown")
                durations_by_name.setdefault(name, []).append(duration)

    result = {}
    for name, durations in durations_by_name.items():
        result[name] = _stats_dict(durations)
    return result


def compute_time_series(
    traces: list[dict],
    span_name: str,
    bucket_minutes: int = 5,
) -> list[dict]:
    """Compute latency stats for a span over time buckets.

    Args:
        bucket_minutes: Must be a positive divisor of 60 (1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60).
            Using non-divisors causes buckets to drift across hour boundaries.

    Returns:
        Sorted list of {"time": iso_string, "p50": float, "p95": float, "mean": float, "count": int}.
    """
    if bucket_minutes <= 0 or 60 % bucket_minutes != 0:
        raise ValueError(f"bucket_minutes must be a positive divisor of 60; got {bucket_minutes}")

    buckets: dict[str, list[float]] = {}

    for trace in traces:
        trace_time = _parse_iso_time(trace.get("start_wall_time_iso", ""))
        if trace_time is None:
            continue

        bucket_ts = trace_time.replace(
            minute=(trace_time.minute // bucket_minutes) * bucket_minutes,
            second=0,
            microsecond=0,
        )
        bucket_key = bucket_ts.isoformat()

        for span in trace.get("spans", []):
            if span.get("name") == span_name:
                duration = span.get("duration_ms")
                if duration is not None and duration >= 0:
                    buckets.setdefault(bucket_key, []).append(duration)

    result = []
    for bucket_key in sorted(buckets):
        entry = _stats_dict(buckets[bucket_key])
        # Time-series chart only needs p50, p95, mean, count — drop the rest for cleanliness.
        result.append(
            {
                "time": bucket_key,
                "p50": entry["p50"],
                "p95": entry["p95"],
                "mean": entry["mean"],
                "count": entry["count"],
            }
        )
    return result


def get_detector_ids(traces: list[dict]) -> list[str]:
    """Extract sorted unique detector IDs from traces."""
    ids = set()
    for trace in traces:
        det_id = trace.get("detector_id")
        if det_id and det_id != "unknown":
            ids.add(det_id)
    return sorted(ids)


def get_trace_detail(traces: list[dict], trace_id: str) -> dict | None:
    """Find a specific trace by ID and return it with spans sorted by start_time_ns.

    Spans for one trace_id can be split across multiple records — the edge endpoint
    and the inference server each write their own record with the same trace_id but
    a disjoint span set. Merge all matching records so the waterfall shows the full
    cross-process tree. Spans are deduped by span_id (first record wins).
    """
    matches = [t for t in traces if t.get("trace_id") == trace_id]
    if not matches:
        return None

    seen_span_ids: set[str] = set()
    merged_spans: list[dict] = []
    for t in matches:
        for s in t.get("spans", []):
            sid = s.get("span_id")
            if sid is not None:
                if sid in seen_span_ids:
                    continue
                seen_span_ids.add(sid)
            merged_spans.append(s)

    result = dict(matches[0])
    result["spans"] = sorted(merged_spans, key=lambda s: s.get("start_time_ns", 0))
    return result


def _stats_dict(durations: list[float]) -> dict:
    """Compute p50/p95/p99/mean/min/max/count for a sample.

    Uses `method='inclusive'` so percentiles are clamped to the observed range.
    """
    count = len(durations)
    if count == 0:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "mean": 0.0, "min": 0.0, "max": 0.0, "count": 0}

    sorted_d = sorted(durations)
    if count >= 2:
        quantiles = statistics.quantiles(sorted_d, n=100, method="inclusive")
        p50 = quantiles[49]
        p95 = quantiles[94]
        p99 = quantiles[98]
    else:
        p50 = p95 = p99 = sorted_d[0]

    return {
        "p50": round(p50, 2),
        "p95": round(p95, 2),
        "p99": round(p99, 2),
        "mean": round(statistics.mean(sorted_d), 2),
        "min": round(sorted_d[0], 2),
        "max": round(sorted_d[-1], 2),
        "count": count,
    }


def _parse_iso_time(iso_string: str) -> datetime | None:
    """Parse an ISO 8601 timestamp string to a timezone-aware datetime.

    Returns None for unparseable strings and for naive (timezone-less) timestamps,
    since comparing naive and aware datetimes raises TypeError.
    """
    if not iso_string:
        return None
    try:
        parsed = datetime.fromisoformat(iso_string)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed
