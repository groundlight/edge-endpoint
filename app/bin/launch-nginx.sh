#!/bin/bash

# Nginx won't refresh the IP address of the upstream endpoint without the "resolver" directive
# but that requires the specific IP address of the DNS server, which can be different in different
# clusters, so we determine that at runtime and edit nginx.conf before starting nginx.

NAME_SERVER=$(awk '/^nameserver / {print $2; exit}' /etc/resolv.conf)
echo "Using nameserver: $NAME_SERVER"

sed "s/__NAME_SERVER__/$NAME_SERVER/" /opt/nginx/nginx.conf > /etc/nginx/nginx.conf

# Note: In production Kubernetes, certificate generation is handled by an initContainer.
# This check is here to support standalone Docker environments and CI.
if [ ! -f /etc/nginx/certs/certificate.crt ]; then
    echo "Generating self-signed TLS certificate..."
    ./app/bin/generate-tls-cert.sh
fi

exec nginx -g "daemon off;"
