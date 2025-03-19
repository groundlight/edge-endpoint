#!/bin/bash

cd $(dirname $0)  # script is in app/bin/ dir
cd ../..

poetry run gunicorn \
    --workers 2 \
    --host 0.0.0.0 \
    --port 8123 \
    app.status_monitor.status_web:app
