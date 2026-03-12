#!/bin/bash

# This script generates a self-signed TLS certificate and key to be used
# by nginx to enable HTTPS.

set -ex

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
mkdir -p /etc/nginx/certs/
cp certificate.crt /etc/nginx/certs/
cp private.key /etc/nginx/certs/

echo "TLS certificate and key copied to /etc/nginx/certs/"

# Clean up
cd /
rm -rf $TMPDIR
