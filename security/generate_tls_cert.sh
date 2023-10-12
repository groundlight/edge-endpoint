#!/bin/bash 

set -ex 

TLS_CERT_DIR=/etc/nginx/ssl

# Generate an Ed25519 Private key 
sudo openssl genpkey -algorithm Ed25519 -out ${TLS_CERT_DIR}/nginx_ed25519.key

# Generate a self-signed certificate using the Ed25519 Private key
# Valid for 365 days
sudo openssl req -x509 -new \
        -key ${TLS_CERT_DIR}/nginx_ed25519.key \
        -out ${TLS_CERT_DIR}/nginx_ed25519.crt \
        -days 365 

