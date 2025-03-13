#!/bin/bash

cd $(dirname $0)

nginx 
poetry run uvicorn \
    --workers 8 \
    --host 0.0.0.0 \
    --port ${APP_PORT} \
    --proxy-headers \
    app.main:app
