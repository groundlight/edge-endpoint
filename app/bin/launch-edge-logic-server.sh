#!/bin/bash

cd $(dirname $0)  # script is in app/bin/ dir
cd ../..

# TODO: We've moved the real nginx into its own container, so we don't need to run it here. This is 
# just here for backwards compatibility since the containers and the chart may not be in sync.

# Note: In production Kubernetes, certificate generation is handled by an initContainer.
# This check is here to support standalone Docker environments and CI.
if [ ! -f /etc/nginx/certs/certificate.crt ]; then
    echo "Generating self-signed TLS certificate..."
    ./app/bin/generate-tls-cert.sh
fi

nginx 

poetry run uvicorn \
    --workers 8 \
    --host 0.0.0.0 \
    --port ${APP_PORT} \
    --proxy-headers \
    app.main:app
