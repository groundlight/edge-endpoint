#!/bin/sh
set -e

MARKER="/opt/groundlight/edge/config/.helm-revision"
DST="/opt/groundlight/edge/config/active-edge-config.yaml"
SRC="/etc/groundlight/edge-config/edge-config.yaml"

STORED_REV=$(cat "$MARKER" 2>/dev/null || echo "")

if [ "$HELM_REVISION" = "$STORED_REV" ]; then
    echo "Helm revision unchanged ($HELM_REVISION), keeping existing active config."
else
    echo "Helm revision changed ($STORED_REV -> $HELM_REVISION)."

    # Only copy if the ConfigMap has real content (not just "{}").
    # When no config file is provided via Helm, we intentionally preserve whatever
    # active config exists on PVC (e.g. config applied via the Python SDK).
    CONTENT=$(cat "$SRC" 2>/dev/null | tr -d '[:space:]')
    if [ -z "$CONTENT" ] || [ "$CONTENT" = "{}" ]; then
        echo "No config file provided via Helm, preserving existing active config."
    else
        mkdir -p "$(dirname "$DST")"
        cp "$SRC" "$DST"
        echo "Active edge config updated from Helm ConfigMap."
    fi

    echo "$HELM_REVISION" > "$MARKER"
fi

# This init container runs as root (busybox default, no securityContext) so it
# can cp/mkdir into a directory that may currently be root-owned from a
# previously-broken run. Chown back to the FIPS edge-endpoint uid afterward,
# unconditionally, so every revision bump self-heals regardless of which
# branch above ran.
chown 65532:65532 "$DST" "$MARKER" 2>/dev/null || true
