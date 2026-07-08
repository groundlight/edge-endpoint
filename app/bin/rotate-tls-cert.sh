#!/bin/bash

# Runs as a long-lived sidecar and periodically ensures the pinned TLS cert is
# fresh, then signals nginx to reload it in place.
#
# generate-tls-cert.sh is idempotent and skips regeneration when the cert is
# still valid, so calling it daily is safe. Sending SIGHUP to nginx afterwards
# is equally harmless when nothing changed: nginx reloads gracefully with no
# dropped connections.
#
# Requires shareProcessNamespace: true on the pod spec so this sidecar can
# signal the nginx master process running in the nginx container.

CERT_DIR="${CERT_DIR:-/etc/nginx/certs}"
CHECK_INTERVAL_SECONDS="${CHECK_INTERVAL_SECONDS:-86400}"

echo "TLS cert rotation watcher started (check interval: ${CHECK_INTERVAL_SECONDS}s)."

while true; do
    sleep "$CHECK_INTERVAL_SECONDS"

    if ! CERT_DIR="$CERT_DIR" /bin/bash /groundlight-edge/app/bin/generate-tls-cert.sh; then
        echo "ERROR: cert generation failed; skipping nginx reload until next check."
        continue
    fi

    nginx_master_pid=$(pgrep -o -f "nginx: master") || true
    if [ -n "$nginx_master_pid" ]; then
        kill -HUP "$nginx_master_pid"
        echo "nginx reloaded (HUP sent to PID $nginx_master_pid)."
    else
        echo "WARNING: nginx master process not found; cert will take effect on next pod restart."
    fi
done
