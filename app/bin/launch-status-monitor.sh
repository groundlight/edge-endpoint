#!/bin/bash

cd $(dirname $0)  # script is in app/bin/ dir
cd ../..

poetry run uvicorn \
    --workers 1 \
    --host 0.0.0.0 \
    --port 8123 \
    app.status_monitor.status_web:app
