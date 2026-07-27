#!/bin/bash

# This script generates a self-signed TLS certificate and key to be used
# by nginx to enable HTTPS.
#
# The certificate is "pinned" to the device: it lives on persistent storage and
# is only (re)generated when the existing cert/key pair is missing, mismatched,
# or within 30 days of expiry. Keeping it stable across pod restarts gives the
# Lens<->edge link a consistent endpoint identity instead of a brand-new cert on
# every boot. Regeneration is self-healing: a broken pair is replaced rather than
# left in place for nginx to choke on later.

set -ex

# CERT_DIR is overridable so the generator can be exercised in tests; production
# deployments mount nginx's cert directory here.
CERT_DIR="${CERT_DIR:-/etc/nginx/certs}"
CERT_FILE="$CERT_DIR/certificate.crt"
KEY_FILE="$CERT_DIR/private.key"

# Reusable means: both files exist, the cert is valid for at least 30 more days,
# and the private key actually matches the certificate.
cert_is_reusable() {
    [ -f "$CERT_FILE" ] || return 1
    [ -f "$KEY_FILE" ] || return 1
    openssl x509 -checkend 2592000 -noout -in "$CERT_FILE" >/dev/null 2>&1 || return 1
    local cert_pubkey key_pubkey
    cert_pubkey=$(openssl x509 -in "$CERT_FILE" -noout -pubkey 2>/dev/null) || return 1
    key_pubkey=$(openssl pkey -in "$KEY_FILE" -pubout 2>/dev/null) || return 1
    [ "$cert_pubkey" = "$key_pubkey" ]
}

if cert_is_reusable; then
    echo "Existing TLS certificate is still valid and matches its key; keeping the pinned cert."
    exit 0
fi

echo "Generating a new self-signed TLS certificate (cert/key missing, mismatched, or near expiry)..."

# create a temporary directory to work in
TMPDIR=$(mktemp -d -t tls-cert-XXXXXX)
cd $TMPDIR

# Generate a private key
openssl genpkey -algorithm RSA -out private.key -pkeyopt rsa_keygen_bits:2048

# Generate a certificate signing request
openssl req -new -key private.key -out csr.pem -subj "/C=US/ST=Washington/L=Seattle/O=Groundlight/OU=Engineering/CN=localhost"

# Generate a self-signed certificate
openssl x509 -req -days 3650 -in csr.pem -signkey private.key -out certificate.crt

echo "TLS certificate and key generated successfully."

# Now copy it to the nginx config directory
mkdir -p "$CERT_DIR"
cp certificate.crt "$CERT_FILE"
cp private.key "$KEY_FILE"

echo "TLS certificate and key copied to $CERT_DIR"

# Clean up
cd /
rm -rf $TMPDIR
