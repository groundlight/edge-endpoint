import logging
import os
from pathlib import Path
from urllib.parse import urlparse

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.core.edge_config_manager import EdgeConfigManager
from app.core.groundlight_client import groundlight_client
from app.metrics.iq_activity import clear_old_activity_files
from app.metrics.metric_reporting import MetricsReporter
from app.metrics.resource_metrics import ResourceMetricsCollector

ONE_HOUR_IN_SECONDS = 3600
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

STATIC_DIR = Path(__file__).parent / "static"
REACT_BUILD_DIR = Path(__file__).parent / "react-build"


def cloud_dashboard_url() -> str:
    """Derive the Cloud Dashboard base URL from the SDK client's configured cloud endpoint.

    Always uses https, since every Groundlight cloud is served over https.
    """
    host = urlparse(groundlight_client().endpoint).hostname
    if not host:
        raise ValueError("Could not determine cloud host from the Groundlight client endpoint.")
    if host.startswith("api."):
        dashboard_host = "dashboard." + host[len("api.") :]
    else:
        dashboard_host = "dashboard." + host
    return f"https://{dashboard_host}"


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


@app.get("/status/edge-config")
def get_edge_config():
    """Return the active edge endpoint configuration as JSON.

    Served here, under the /status prefix, so the status page can read it through the same
    reverse proxy that fronts the rest of the status UI (e.g. the GEP hub). The main
    edge-endpoint API also exposes /edge-config for SDK and tooling use.
    """
    return EdgeConfigManager.active().to_payload()


@app.get("/status/cloud-config")
def get_cloud_config():
    """Return cloud-derived config for the status UI, such as the Cloud Dashboard base
    URL used to build detector links."""
    return {"dashboard_url": cloud_dashboard_url()}


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
