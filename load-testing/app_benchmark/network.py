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
    parsed = urlparse(url)
    return parsed.hostname or None


def _is_loopback(host: str) -> bool:
    return host in {"localhost", "127.0.0.1", "::1"} or host.startswith("127.")


def measure(host: str | None, packet_count: int = 5, timeout_s: int = 5) -> dict | None:
    """ICMP ping `host` `packet_count` times. Returns RTT stats in ms,
    or None if loopback / ping unavailable / unreachable."""
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
    if stats is None:
        if host and _is_loopback(host):
            return "loopback — skipped"
        return "unavailable"
    return (
        f"min {stats['min_ms']:.2f} ms · avg {stats['avg_ms']:.2f} ms · "
        f"max {stats['max_ms']:.2f} ms · σ {stats['stddev_ms']:.2f} ms "
        f"({stats['packets']} pkts to {stats['host']})"
    )
