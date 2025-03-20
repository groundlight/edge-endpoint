import logging
import os
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.metrics.metricreporting import metrics_payload, report_metrics_to_cloud

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
# Environment variable lets us speed up testing
STATUS_REPORT_INTERVAL = int(os.environ.get("STATUS_REPORT_INTERVAL", 3600))


app = FastAPI(title="status-monitor")
scheduler = AsyncIOScheduler()

@app.on_event("startup")
async def startup_event():
    """Lifecycle event that is triggered when the application starts."""
    logging.basicConfig(
        level=LOG_LEVEL, format="%(asctime)s.%(msecs)03d %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    logging.info("Starting status-monitor server...")
    scheduler.add_job(report_metrics_to_cloud, "interval", seconds=STATUS_REPORT_INTERVAL)
    logging.info("Will report metrics to cloud every %d seconds", STATUS_REPORT_INTERVAL)
    scheduler.start()


@app.get("/status/metrics.json")
async def get_metrics():
    """Return system metrics as JSON."""
    return metrics_payload()


@app.get("/status")
async def get_status():
    """Serve the status monitoring HTML page."""
    html_path = Path(__file__).parent / "static" / "status.html"
    with open(html_path, "r") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)
