#!/bin/sh
set -e

MARKER="/opt/groundlight/edge/config/.helm-revision"
DST="/opt/groundlight/edge/config/active-edge-config.yaml"
SRC="/etc/groundlight/edge-config/edge-config.yaml"

STORED_REV=$(cat "$MARKER" 2>/dev/null || echo "")

if [ "$HELM_REVISION" = "$STORED_REV" ]; then
    echo "Helm revision unchanged ($HELM_REVISION), keeping existing active config."
    exit 0
fi

echo "Helm revision changed ($STORED_REV -> $HELM_REVISION)."

# Only copy if the ConfigMap has real content (not just "{}")
CONTENT=$(cat "$SRC" 2>/dev/null | tr -d '[:space:]')
if [ -z "$CONTENT" ] || [ "$CONTENT" = "{}" ]; then
    echo "No config file provided via Helm, skipping."
else
    mkdir -p "$(dirname "$DST")"
    cp "$SRC" "$DST"
    echo "Active edge config updated from Helm ConfigMap."
fi

echo "$HELM_REVISION" > "$MARKER"
