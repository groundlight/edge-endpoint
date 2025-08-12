#!/usr/bin/env bash
set -euo pipefail

# Enable Toxiproxy for the Edge Endpoint by:
# 1) Deploying toxiproxy (Deployment + Service) in the given namespace
# 2) Configuring a proxy 'gl' to forward to the current IP of api.groundlight.ai:443
# 3) Patching the EE Deployment to map api.groundlight.ai -> Toxiproxy ClusterIP via hostAliases

NAMESPACE=${1:-edge}
EE_DEPLOYMENT=${2:-edge-endpoint}
CLOUD_HOST=${3:-api.groundlight.ai}

echo "Applying Toxiproxy resources in namespace: $NAMESPACE"
kubectl -n "$NAMESPACE" apply -f "$(dirname "$0")/toxiproxy.yaml"

echo "Waiting for toxiproxy Deployment to be ready..."
kubectl -n "$NAMESPACE" rollout status deploy/toxiproxy --timeout=120s

echo "Resolving current IP for $CLOUD_HOST from cluster..."
UPSTREAM_IP=$(kubectl -n "$NAMESPACE" run dnsutils-ttx --rm -i --restart=Never --image=busybox:1.36 --command -- sh -c "nslookup $CLOUD_HOST 2>/dev/null | awk '/^Address /{print \$3}' | tail -n1")
if [ -z "$UPSTREAM_IP" ]; then
  echo "Failed to resolve $CLOUD_HOST inside cluster" >&2
  exit 1
fi
echo "Resolved $CLOUD_HOST -> $UPSTREAM_IP"

ADMIN_SVC=toxiproxy
ADMIN_PORT=8474

echo "Creating proxy gl in toxiproxy: 0.0.0.0:443 -> $UPSTREAM_IP:443"
kubectl -n "$NAMESPACE" run toxiproxy-bootstrap --rm -i --restart=Never --image=curlimages/curl:8.9.1 --command -- sh -c \
  "curl -sX POST http://$ADMIN_SVC:$ADMIN_PORT/proxies -H 'Content-Type: application/json' -d '{\"name\":\"gl\",\"listen\":\"0.0.0.0:443\",\"upstream\":\"$UPSTREAM_IP:443\"}' || true"

CLUSTER_IP=$(kubectl -n "$NAMESPACE" get svc toxiproxy -o jsonpath='{.spec.clusterIP}')
if [ -z "$CLUSTER_IP" ]; then
  echo "Failed to get toxiproxy Service ClusterIP" >&2
  exit 1
fi
echo "Toxiproxy Service ClusterIP: $CLUSTER_IP"

PATCH=$(cat <<EOF
{
  "spec": {
    "template": {
      "spec": {
        "hostAliases": [
          {"ip": "$CLUSTER_IP", "hostnames": ["$CLOUD_HOST"]}
        ]
      }
    }
  }
}
EOF
)

echo "Patching Deployment/$EE_DEPLOYMENT to add hostAliases mapping $CLOUD_HOST -> $CLUSTER_IP"
kubectl -n "$NAMESPACE" patch deploy "$EE_DEPLOYMENT" --type merge -p "$PATCH"

echo "Done. EE traffic to $CLOUD_HOST will now be routed via Toxiproxy."

