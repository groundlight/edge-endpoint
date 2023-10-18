#!/bin/bash 

set -ex 

# Change to current directory 
cd $(dirname $0)

# Set TLS_CERT_DIR to current directory
TLS_CERT_DIR=$(pwd)/ssl

# Generate an Ed25519 Private key 
sudo openssl genpkey -algorithm Ed25519 -out ${TLS_CERT_DIR}/nginx_ed25519.key

# Generate a self-signed certificate using the Ed25519 Private key
# Valid for 365 days
sudo openssl req -new -x509 \
        -config openssl-custom.cnf \
        -batch \
        -key ${TLS_CERT_DIR}/nginx_ed25519.key \
        -out ${TLS_CERT_DIR}/nginx_ed25519.crt \
        -days 365 

