import logging
import os
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.metrics.metric_reporting import MetricsReporter
from app.metrics.iq_activity import clear_old_activity_files

ONE_HOUR_IN_SECONDS = 3600
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

app = FastAPI(title="status-monitor")
scheduler = AsyncIOScheduler()
reporter = MetricsReporter()


@app.on_event("startup")
async def startup_event():
    """Lifecycle event that is triggered when the application starts."""
    logging.basicConfig(
        level=LOG_LEVEL, format="%(asctime)s.%(msecs)03d %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    logging.info("Starting status-monitor server...")
    logging.info("Will report metrics to the cloud every hour")
    scheduler.add_job(reporter.collect_metrics_for_cloud, "cron", hour="*", minute="1")
    scheduler.add_job(reporter.report_metrics_to_cloud, "cron", hour="*", minute="2", jitter=120)
    scheduler.add_job(clear_old_activity_files, "interval", seconds=ONE_HOUR_IN_SECONDS)
    scheduler.start()


@app.get("/status/metrics.json")
async def get_metrics():
    """Return system metrics as JSON."""
    return reporter.metrics_payload()


@app.get("/status")
async def get_status():
    """Serve the status monitoring HTML page."""
    html_path = Path(__file__).parent / "static" / "status.html"
    with open(html_path, "r") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)
