#!/usr/bin/env bash
set -euo pipefail

# Disable Toxiproxy for the Edge Endpoint by removing the hostAliases patch and deleting the toxiproxy resources.

NAMESPACE=${1:-edge}
EE_DEPLOYMENT=${2:-edge-endpoint}
CLOUD_HOST=${3:-api.groundlight.ai}

echo "Removing hostAliases mapping from Deployment/$EE_DEPLOYMENT (if present)"
PATCH=$(cat <<'EOF'
{
  "spec": {
    "template": {
      "spec": {
        "hostAliases": null
      }
    }
  }
}
EOF
)
kubectl -n "$NAMESPACE" patch deploy "$EE_DEPLOYMENT" --type merge -p "$PATCH" || true

echo "Deleting toxiproxy resources"
kubectl -n "$NAMESPACE" delete -f "$(dirname "$0")/toxiproxy.yaml" --ignore-not-found

echo "Done. EE traffic to $CLOUD_HOST now goes directly to the cloud again."

