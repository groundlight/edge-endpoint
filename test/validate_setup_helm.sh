#!/bin/bash
# basic script to validate that helm installation works as expected

set -e

export DEPLOYMENT_NAMESPACE="validate-setup-helm"
export INFERENCE_FLAVOR="CPU"
export EDGE_ENDPOINT_PORT="30106"

export HELM_RELEASE_NAME="$DEPLOYMENT_NAMESPACE"

if [ -z "${GROUNDLIGHT_API_TOKEN}" ]; then
    echo "Error: GROUNDLIGHT_API_TOKEN environment variable must be set."
    exit 1
fi

if [ -n "$(kubectl get namespace $DEPLOYMENT_NAMESPACE --ignore-not-found)" ]; then
    echo "Namespace $DEPLOYMENT_NAMESPACE already exists. Delete it before running this script."
    exit 1
fi

# Run from the root of the repo
cd $(dirname $0)/.. 

echo "Installing edge-endpoint helm chart..."
# TODO: which container images do we want to use?
helm install -n default ${HELM_RELEASE_NAME} deploy/helm/groundlight-edge-endpoint \
    --set groundlightApiToken=$GROUNDLIGHT_API_TOKEN \
    --set inferenceFlavor=$INFERENCE_FLAVOR \
    --set edgeEndpointPort=$EDGE_ENDPOINT_PORT \
    --set namespace=$DEPLOYMENT_NAMESPACE


echo "Waiting for edge-endpoint pods to rollout in namespace $DEPLOYMENT_NAMESPACE..."

if ! kubectl rollout status deployment/edge-endpoint -n $DEPLOYMENT_NAMESPACE --timeout=5m; then
    echo "Error: edge-endpoint pods failed to rollout within the timeout period."
    
    echo Debugging information:
    set -x
    kubectl get pods -n $DEPLOYMENT_NAMESPACE
    kubectl describe -n $DEPLOYMENT_NAMESPACE $(kubectl get -n $DEPLOYMENT_NAMESPACE pods -o name | grep edge-endpoint)
    kubectl logs -n $DEPLOYMENT_NAMESPACE deployment/edge-endpoint

    helm uninstall ${HELM_RELEASE_NAME} -n default
    exit 1
fi

echo "Edge-endpoint pods have successfully rolled out in namespace $DEPLOYMENT_NAMESPACE."

echo "Deleting helm deployment..."
helm uninstall ${HELM_RELEASE_NAME} -n default

echo "Waiting for namespace $DEPLOYMENT_NAMESPACE to terminate..."
if ! kubectl wait --for=delete namespace/$DEPLOYMENT_NAMESPACE --timeout=5m; then
    echo "Error: namespace $DEPLOYMENT_NAMESPACE failed to terminate within the timeout period."
    exit 1
fi

echo "Namespace $DEPLOYMENT_NAMESPACE has been successfully deleted."
echo "Test completed successfully."