"""Network latency baseline (ICMP ping) before the benchmark starts.

Skips loopback hosts — pinging localhost just measures the kernel and tells
you nothing about real-world transport. Returns None when ping is unavailable
or the host is unreachable; callers should treat None as "no baseline".
"""

import re
import subprocess
from urllib.parse import urlparse

_PING_OUTPUT_RE = re.compile(r"=\s*([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)\s*ms")


def host_from_url(url: str) -> str | None:
    """Extract the hostname portion of `url` (e.g. "10.1.2.3" from
    "http://10.1.2.3:30101"). Returns None when the URL has no host."""
    parsed = urlparse(url)
    return parsed.hostname or None


def _is_loopback(host: str) -> bool:
    """True for localhost / 127.x.x.x / IPv6 ::1."""
    return host in {"localhost", "127.0.0.1", "::1"} or host.startswith("127.")


def measure(host: str | None, packet_count: int = 5, timeout_s: int = 5) -> dict | None:
    """Measure ICMP round-trip latency to `host` and return the stats.

    Args:
        host: Hostname or IP. Loopback hosts return None (pinging
            localhost only measures the kernel — not useful as a
            network baseline).
        packet_count: Number of ICMP echo requests to send.
        timeout_s: Per-packet timeout in seconds passed to `ping -W`.

    Returns:
        Dict with keys {host, packets, min_ms, avg_ms, max_ms, stddev_ms}
        on success. None when the host is loopback, the `ping` binary
        is missing, the host is unreachable, or the ping output couldn't
        be parsed.
    """
    if not host or _is_loopback(host):
        return None
    try:
        result = subprocess.run(
            ["ping", "-c", str(packet_count), "-W", str(timeout_s), host],
            capture_output=True, text=True,
            timeout=timeout_s * packet_count + 5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    match = _PING_OUTPUT_RE.search(result.stdout)
    if not match:
        return None
    return {
        "host": host,
        "packets": packet_count,
        "min_ms": float(match.group(1)),
        "avg_ms": float(match.group(2)),
        "max_ms": float(match.group(3)),
        "stddev_ms": float(match.group(4)),
    }


def format_summary(stats: dict | None, host: str | None = None) -> str:
    """Render a one-line ping summary for summary.md.

    Args:
        stats: The dict returned by `measure(...)`, or None.
        host: Original host string (only used to distinguish the
            "loopback — skipped" case from a hard failure).

    Returns:
        Human-readable string. Either:
            - "min ... ms · avg ... ms · max ... ms · σ ... ms (N pkts to HOST)"
            - "loopback — skipped" when host is loopback and stats is None
            - "unavailable" when stats is None for any other reason
    """
    if stats is None:
        if host and _is_loopback(host):
            return "loopback — skipped"
        return "unavailable"
    return (
        f"min {stats['min_ms']:.2f} ms · avg {stats['avg_ms']:.2f} ms · "
        f"max {stats['max_ms']:.2f} ms · σ {stats['stddev_ms']:.2f} ms "
        f"({stats['packets']} pkts to {stats['host']})"
    )
