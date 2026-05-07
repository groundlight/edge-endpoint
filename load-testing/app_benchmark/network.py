"""ICMP ping latency to the edge endpoint, used as a baseline in the report."""

import logging
import re
import shutil
import subprocess
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_RTT_RE = re.compile(
    r"(?:round-trip|rtt)\s+min/avg/max/(?:stddev|mdev)\s*=\s*"
    r"([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)"
)


def host_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    return parsed.hostname


def measure(host: str, count: int = 5, per_ping_timeout_s: float = 2.0) -> dict | None:
    """Run system `ping -c <count> <host>` and parse the rtt summary line.

    Returns dict with min_ms / avg_ms / max_ms / stddev_ms / count, or None
    if ping isn't installed, the host is unreachable, or output couldn't
    be parsed (e.g. firewall blocks ICMP).
    """
    if shutil.which("ping") is None:
        logger.info("ping not installed; skipping latency baseline",
                    extra={"phase": "startup"})
        return None
    try:
        result = subprocess.run(
            ["ping", "-c", str(count), host],
            capture_output=True, text=True,
            timeout=per_ping_timeout_s * count + 5,
        )
    except subprocess.TimeoutExpired:
        logger.warning("ping %s timed out", host, extra={"phase": "startup"})
        return None
    except Exception as exc:
        logger.warning("ping %s failed: %s", host, exc, extra={"phase": "startup"})
        return None

    if result.returncode != 0:
        logger.warning("ping %s returned %d (host unreachable or ICMP blocked)",
                       host, result.returncode, extra={"phase": "startup"})
        return None

    match = _RTT_RE.search(result.stdout)
    if not match:
        logger.warning("could not parse ping output for %s", host,
                       extra={"phase": "startup"})
        return None

    return {
        "host": host,
        "count": count,
        "min_ms": float(match.group(1)),
        "avg_ms": float(match.group(2)),
        "max_ms": float(match.group(3)),
        "stddev_ms": float(match.group(4)),
    }


def format_summary(latency: dict | None) -> str:
    if latency is None:
        return "(unavailable)"
    return (
        f"{latency['count']} pings to {latency['host']}: "
        f"min/avg/max/stddev = "
        f"{latency['min_ms']:.3f}/{latency['avg_ms']:.3f}/"
        f"{latency['max_ms']:.3f}/{latency['stddev_ms']:.3f} ms"
    )
