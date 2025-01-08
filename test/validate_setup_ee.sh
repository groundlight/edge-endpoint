#!/bin/bash
# basic script to validate that setup_ee works as expected
export DEPLOYMENT_NAMESPACE="validate-setup-ee"
export INFERENCE_FLAVOR="CPU"

kubectl create namespace $DEPLOYMENT_NAMESPACE
./deploy/bin/setup-ee.sh

echo "Waiting for edge-endpoint pods to rollout in namespace $DEPLOYMENT_NAMESPACE..."

if ! kubectl rollout status deployment/edge-endpoint -n $DEPLOYMENT_NAMESPACE --timeout=5m; then
    echo "Error: edge-endpoint pods failed to rollout within the timeout period."
    exit 1
fi

echo "Edge-endpoint pods have successfully rolled out in namespace $DEPLOYMENT_NAMESPACE."

echo "Deleting persistant volume and persistant volume claim..."
kubectl delete pv edge-endpoint-pv
kubectl delete pv edge-endpoint-pvc -n $DEPLOYMENT_NAMESPACE