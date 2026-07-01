#!/bin/bash

# This script generates a self-signed TLS certificate and key to be used
# by nginx to enable HTTPS.
#
# The certificate is "pinned" to the device: it lives on persistent storage and
# is only (re)generated when it is missing or within 30 days of expiry. Keeping
# it stable across pod restarts gives the Lens<->edge link a consistent endpoint
# identity instead of a brand-new cert on every boot.

set -ex

CERT_DIR=/etc/nginx/certs
CERT_FILE="$CERT_DIR/certificate.crt"
KEY_FILE="$CERT_DIR/private.key"

# Reuse the existing cert if it is present and valid for at least 30 more days.
if [ -f "$CERT_FILE" ] && [ -f "$KEY_FILE" ] && openssl x509 -checkend 2592000 -noout -in "$CERT_FILE"; then
    echo "Existing TLS certificate is still valid; keeping the pinned cert."
    exit 0
fi

echo "Generating a new self-signed TLS certificate..."

# create a temporary directory to work in
TMPDIR=$(mktemp -d -t tls-cert-XXXXXX)
cd $TMPDIR

# Generate a private key
openssl genpkey -algorithm RSA -out private.key -pkeyopt rsa_keygen_bits:2048

# Generate a certificate signing request
openssl req -new -key private.key -out csr.pem -subj "/C=US/ST=Washington/L=Seattle/O=Groundlight/OU=Engineering/CN=localhost"

# Generate a self-signed certificate
openssl x509 -req -days 365 -in csr.pem -signkey private.key -out certificate.crt

echo "TLS certificate and key generated successfully."

# Now copy it to the nginx config directory
mkdir -p "$CERT_DIR"
cp certificate.crt "$CERT_FILE"
cp private.key "$KEY_FILE"

echo "TLS certificate and key copied to $CERT_DIR"

# Clean up
cd /
rm -rf $TMPDIR
