#!/bin/bash

# Runs as a long-lived sidecar and periodically checks whether the pinned TLS
# cert needs rotation. If the cert is missing, mismatched, or within 30 days of
# expiry it regenerates the cert and sends SIGHUP to the nginx master process for
# an in-place reload without restarting the pod.
#
# Requires shareProcessNamespace: true on the pod spec so this sidecar can signal
# the nginx master process running in the nginx container.

CERT_DIR="${CERT_DIR:-/etc/nginx/certs}"
CERT_FILE="$CERT_DIR/certificate.crt"
KEY_FILE="$CERT_DIR/private.key"

# Mirrors the cert_is_reusable check in generate-tls-cert.sh.
cert_is_reusable() {
    [ -f "$CERT_FILE" ] || return 1
    [ -f "$KEY_FILE" ] || return 1
    openssl x509 -checkend 2592000 -noout -in "$CERT_FILE" >/dev/null 2>&1 || return 1
    local cert_pubkey key_pubkey
    cert_pubkey=$(openssl x509 -in "$CERT_FILE" -noout -pubkey 2>/dev/null) || return 1
    key_pubkey=$(openssl pkey -in "$KEY_FILE" -pubout 2>/dev/null) || return 1
    [ "$cert_pubkey" = "$key_pubkey" ]
}

CHECK_INTERVAL_SECONDS="${CHECK_INTERVAL_SECONDS:-86400}"

echo "TLS cert rotation watcher started (check interval: ${CHECK_INTERVAL_SECONDS}s)."

while true; do
    sleep "$CHECK_INTERVAL_SECONDS"

    if cert_is_reusable; then
        echo "TLS cert is valid; no rotation needed."
        continue
    fi

    echo "TLS cert is missing, mismatched, or near expiry; regenerating..."
    CERT_DIR="$CERT_DIR" /bin/bash /groundlight-edge/app/bin/generate-tls-cert.sh

    nginx_master_pid=$(pgrep -o -f "nginx: master") || true
    if [ -n "$nginx_master_pid" ]; then
        kill -HUP "$nginx_master_pid"
        echo "TLS cert rotated and nginx reloaded (HUP sent to PID $nginx_master_pid)."
    else
        echo "WARNING: cert regenerated but nginx master process not found; reload will take effect on next pod restart."
    fi
done
