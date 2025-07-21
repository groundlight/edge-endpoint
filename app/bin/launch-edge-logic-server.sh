#!/bin/bash

cd $(dirname $0)  # script is in app/bin/ dir
cd ../..

# TODO: We've moved the real nginx into its own container, so we don't need to run it here. This is 
# just here for backwards compatibility since the containers and the chart may not be in sync.

nginx 

poetry run uvicorn \
    --workers 1 \
    --host 0.0.0.0 \
    --port ${APP_PORT} \
    --proxy-headers \
    app.main:app
