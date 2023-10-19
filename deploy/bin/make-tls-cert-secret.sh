#!/bin/bash

K="k3s kubectl"
TLS_PRIVATE_KEY="certs/ssl/nginx_ed25519.key"
TLS_CERTIFICATE="certs/ssl/nginx_ed25519.crt"

$K delete --ignore-not-found secret tls-certificate


# First check if the certs/ssl/nginx_ed25519.key and certs/ssl/nginx_ed25519.crt exist
# If not exit early with an error message
if [ ! -f "$TLS_PRIVATE_KEY" ] || [ ! -f "$TLS_CERTIFICATE" ]; then
    echo "TLS certificate and key not found at the desired location. Exiting..."
    exit 1
fi


# Create a kubernetes secret for the groundlight api token
# Make sure that you have the groundlight api token set in your environment

$K create secret generic tls-certificate \
    --from-file=nginx_ed25519.key=${TLS_PRIVATE_KEY} \
    --from-file=nginx_ed25519.crt=${TLS_CERTIFICATE}