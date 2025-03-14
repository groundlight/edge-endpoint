#!/bin/bash

cd $(dirname $0)  # script is in app/ dir
cd ..  

# TODO: We should move nginx to its own container
nginx 

poetry run uvicorn \
    --workers 8 \
    --host 0.0.0.0 \
    --port ${APP_PORT} \
    --proxy-headers \
    app.main:app
