import logging
import os
from pathlib import Path
from urllib.parse import urlparse

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.metrics.iq_activity import clear_old_activity_files
from app.metrics.metric_reporting import MetricsReporter
from app.metrics.resource_metrics import ResourceMetricsCollector

ONE_HOUR_IN_SECONDS = 3600
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# The production Groundlight dashboard. Used as a fallback when the upstream
# endpoint is unset or doesn't follow the conventional api.<env>.groundlight.ai
# naming (e.g. localhost, an IP address, or a custom hostname).
DEFAULT_DASHBOARD_URL = "https://dashboard.groundlight.ai"


def dashboard_base_url() -> str:
    """Derive the Groundlight dashboard base URL from the upstream API endpoint.

    The Edge Endpoint forwards to an upstream Groundlight service configured via
    the GROUNDLIGHT_ENDPOINT env var. Each environment's API host is conventionally
    named ``api.<env>.groundlight.ai`` (e.g. ``api.groundlight.ai`` for prod,
    ``api.integ.groundlight.ai`` for integ) and its dashboard lives at the matching
    ``dashboard.<env>.groundlight.ai``. We swap the leading ``api`` label for
    ``dashboard`` so detector links on the status page open the dashboard for the
    environment this endpoint is actually connected to, rather than always prod.

    Falls back to the production dashboard for anything non-standard so links
    remain functional.
    """
    endpoint = os.environ.get("GROUNDLIGHT_ENDPOINT", "").strip()
    if not endpoint:
        return DEFAULT_DASHBOARD_URL
    parsed = urlparse(endpoint if "://" in endpoint else f"https://{endpoint}")
    host = parsed.hostname or ""
    labels = host.split(".")
    if labels and labels[0] == "api":
        labels[0] = "dashboard"
        return f"{parsed.scheme}://{'.'.join(labels)}"
    return DEFAULT_DASHBOARD_URL


STATIC_DIR = Path(__file__).parent / "static"
REACT_BUILD_DIR = Path(__file__).parent / "react-build"

app = FastAPI(title="status-monitor")
scheduler = AsyncIOScheduler()
reporter = MetricsReporter()
resource_collector = ResourceMetricsCollector()


@app.on_event("startup")
async def startup_event():
    """Lifecycle event that is triggered when the application starts."""
    logging.basicConfig(
        level=LOG_LEVEL, format="%(asctime)s.%(msecs)03d %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    logging.info("Starting status-monitor server...")
    logging.info("Will report metrics to the cloud every hour")
    # Every hour, on the hour, collect metrics to send to the cloud.
    scheduler.add_job(reporter.collect_metrics_for_cloud, "cron", hour="*", minute="0")
    # Every hour, try to report collected metrics to the cloud. Run at 3 minutes past the hour, with a jitter of 120
    # seconds, to avoid every edge-endpoint report hitting the server at the exact same time.
    scheduler.add_job(reporter.report_metrics_to_cloud, "cron", hour="*", minute="3", jitter=120)
    scheduler.add_job(clear_old_activity_files, "interval", seconds=ONE_HOUR_IN_SECONDS)
    scheduler.start()


@app.get("/status/metrics.json")
async def get_metrics():
    """Return system metrics as JSON."""
    return reporter.metrics_payload()


@app.get("/status/resources.json")
def get_resources():
    """Return per-detector GPU and RAM usage as JSON."""
    return resource_collector.collect()


@app.get("/status/config.json")
def get_config():
    """Return static frontend config, e.g. the dashboard URL for detector links.

    Derived from the upstream endpoint so links open the correct environment's
    dashboard (prod, integ, dev, etc.) instead of always pointing at prod.
    """
    return {"dashboard_url": dashboard_base_url()}


@app.get("/status")
async def get_status():
    """Serve the React status page."""
    html_path = REACT_BUILD_DIR / "index.html"
    with open(html_path, "r") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)


# Favicon and logo served from the original static dir
app.mount("/status/static", StaticFiles(directory=STATIC_DIR), name="status-static")
# Vite-built React assets (JS, CSS bundles)
app.mount("/status", StaticFiles(directory=REACT_BUILD_DIR), name="status-react")
