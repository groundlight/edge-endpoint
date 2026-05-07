import json
import logging
import sys
import time
from pathlib import Path
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": record.created,
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in ("run_name", "phase", "lens", "client", "detector_id"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class _ConsoleFormatter(logging.Formatter):
    """Compact human-readable: 'HH:MM:SS [level] logger: msg'.

    Drops the noisy timestamp/level/JSON noise from stdout. The full structured
    JSON record is still written to run.log via JsonFormatter.
    """

    def format(self, record: logging.LogRecord) -> str:
        ts = time.strftime("%H:%M:%S", time.gmtime(record.created))
        # Trim "app_benchmark." prefix to keep lines short.
        name = record.name.removeprefix("app_benchmark.")
        msg = record.getMessage()
        if record.exc_info:
            msg = f"{msg} | {self.formatException(record.exc_info)}"
        return f"{ts} [{record.levelname}] {name}: {msg}"


def configure(output_dir: Path | None = None, level: int = logging.INFO, run_name: str | None = None) -> None:
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    stdout = logging.StreamHandler(sys.stdout)
    stdout.setFormatter(_ConsoleFormatter())
    root.addHandler(stdout)

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(output_dir / "run.log")
        file_handler.setFormatter(JsonFormatter())
        root.addHandler(file_handler)

    if run_name:
        old_factory = logging.getLogRecordFactory()

        def factory(*args, **kwargs):
            record = old_factory(*args, **kwargs)
            record.run_name = run_name
            return record

        logging.setLogRecordFactory(factory)

    logging.Formatter.converter = time.gmtime
