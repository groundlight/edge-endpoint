#!/bin/bash

# This script will setup the k3s testing environment. Once you've run them you can run the
# live tests, which will hit the API service that got setup
# Altogether, you can run everything with:
# > make test-with-k3s

if [ -z "$GROUNDLIGHT_API_TOKEN" ]; then
    echo "Error: GROUNDLIGHT_API_TOKEN environment variable is not set."
    exit 1
fi

if ! command -v k3s &> /dev/null
then
    echo "Error: you must have k3s setup"
    exit 1
fi
export PERSISTENT_VOLUME_NAME="test-with-k3s-pv"
export EDGE_ENDPOINT_PORT="30107"

# # now we should delete the persistent volume before, in case it's in a bad state
# Check if the persistent volume exists
if kubectl get pv "$PERSISTENT_VOLUME_NAME" &> /dev/null; then
    echo "Persistent volume $PERSISTENT_VOLUME_NAME exists. Deleting it..."
    kubectl delete pv "$PERSISTENT_VOLUME_NAME" &
    echo "Persistent volume $PERSISTENT_VOLUME_NAME deleted."
else
    echo "Persistent volume $PERSISTENT_VOLUME_NAME does not exist. No action needed."
fi


export DEPLOYMENT_NAMESPACE="test-with-k3s"
if ! kubectl get namespace $DEPLOYMENT_NAMESPACE &> /dev/null; then
    kubectl create namespace $DEPLOYMENT_NAMESPACE
fi

# Build the Docker image and import it into k3s
echo "Building the Docker image..."
ls
../deploy/bin/build-push-edge-endpoint-image.sh dev
export IMAGE_TAG=$(../deploy/bin/git-tag-name.sh)

export INFERENCE_FLAVOR="CPU"
../deploy/bin/setup-ee.sh

export LIVE_TEST_ENDPOINT="http://localhost:$EDGE_ENDPOINT_PORT"
echo "Waiting for edge-endpoint pods to rollout..."

if ! kubectl rollout status deployment/edge-endpoint -n $DEPLOYMENT_NAMESPACE --timeout=5m; then
    echo "Error: edge-endpoint pods failed to rollout within the timeout period."
    exit 1
fi

echo "Edge-endpoint pods have successfully rolled out."

