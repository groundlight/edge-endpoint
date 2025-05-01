#!/bin/bash

# This script will setup the k3s testing environment. Once you've run them you can run the
# live tests, which will hit the API service that got setup
# Altogether, you can run everything with:
# > make test-with-k3s-helm
set -e
set -x

if [ -z "$GROUNDLIGHT_API_TOKEN" ]; then
    echo "Error: GROUNDLIGHT_API_TOKEN environment variable is not set."
    exit 1
fi

if ! command -v k3s &> /dev/null
then
    echo "Error: you must have k3s setup"
    exit 1

fi

echo $GROUNDLIGHT_ENDPOINT 

# First create a detector to use for testing:
export DETECTOR_ID=$(poetry run python test/integration/integration.py --mode create_detector)
echo "created detector with id: $DETECTOR_ID"

# set some other environment variables
# We put the tests on port 30108 and in a different namespace so that it doesn't require any
# extra configuration to run them alongside a "default" deployment while you're developing.
export EDGE_ENDPOINT_PORT="30108"
export DEPLOYMENT_NAMESPACE="test-with-k3s-helm"
export INFERENCE_FLAVOR="CPU"
export LIVE_TEST_ENDPOINT="http://localhost:$EDGE_ENDPOINT_PORT"
export REFRESH_RATE=60 # not actually different than the default, but we may want to tweak this

# update the config for this detector, such that we always take edge answers
# but first, save the template to a temporary file
EDGE_CONFIG_FILE="/tmp/edge-config.$$.yaml"

cp deploy/helm/groundlight-edge-endpoint/files/default-edge-config.yaml $EDGE_CONFIG_FILE
sed -i "s/detector_id: \"\"/detector_id: \"$DETECTOR_ID\"/" $EDGE_CONFIG_FILE
sed -i "s/refresh_rate: 60/refresh_rate: $REFRESH_RATE/" $EDGE_CONFIG_FILE

trap 'rm -rf "$EDGE_CONFIG_FILE"' EXIT

if [ -n "$(kubectl get namespace $DEPLOYMENT_NAMESPACE --ignore-not-found)" ]; then
    echo "Namespace $DEPLOYMENT_NAMESPACE already exists. Delete it before running this script."
    exit 1
fi

export HELM_RELEASE_NAME="$DEPLOYMENT_NAMESPACE"

export IMAGE_TAG=$(./deploy/bin/git-tag-name.sh)
echo "Using ECR edge-endpoint image tag: $IMAGE_TAG"

# Run the helm chart
echo "Installing edge-endpoint helm chart..."
echo "INFERENCE_FLAVOR: $INFERENCE_FLAVOR"
echo "DEPLOYMENT_NAMESPACE: $DEPLOYMENT_NAMESPACE"
echo "IMAGE_TAG: $IMAGE_TAG"
echo "INFERENCE_IMAGE_TAG: $INFERENCE_IMAGE_TAG"
helm install -n default ${HELM_RELEASE_NAME} deploy/helm/groundlight-edge-endpoint \
    --set groundlightApiToken=$GROUNDLIGHT_API_TOKEN \
    --set inferenceFlavor=$INFERENCE_FLAVOR \
    --set edgeEndpointPort=$EDGE_ENDPOINT_PORT \
    --set namespace=$DEPLOYMENT_NAMESPACE \
    --set edgeEndpointTag=$IMAGE_TAG \
    --set inferenceTag=$INFERENCE_IMAGE_TAG \
    --set-file configFile=$EDGE_CONFIG_FILE

echo "Waiting for edge-endpoint pods to rollout..."

if ! kubectl rollout status deployment/edge-endpoint -n $DEPLOYMENT_NAMESPACE --timeout=5m; then
    echo "Error: edge-endpoint pods failed to rollout within the timeout period."
    exit 1
fi

echo "Edge-endpoint pods have successfully rolled out."

echo "Waiting for the inference deployments to rollout (inferencemodel-primary-$DETECTOR_ID) and (inferencemodel-oodd-$DETECTOR_ID)..."

export DETECTOR_ID_WITH_DASHES=$(echo ${DETECTOR_ID//_/-} | tr '[:upper:]' '[:lower:]')
sleep 60

echo "Describing the inferencemodel pod (inferencemodel-primary-$DETECTOR_ID_WITH_DASHES)..."
kubectl describe pod -l app=inferencemodel-primary-$DETECTOR_ID_WITH_DASHES -n $DEPLOYMENT_NAMESPACE

echo "Describing the inferencemodel pod (inferencemodel-oodd-$DETECTOR_ID_WITH_DASHES)..."
kubectl describe pod -l app=inferencemodel-oodd-$DETECTOR_ID_WITH_DASHES -n $DEPLOYMENT_NAMESPACE

# Run both rollout checks in parallel
kubectl rollout status deployment/inferencemodel-primary-$DETECTOR_ID_WITH_DASHES \
    -n $DEPLOYMENT_NAMESPACE --timeout=10m &
primary_pid=$!

kubectl rollout status deployment/inferencemodel-oodd-$DETECTOR_ID_WITH_DASHES \
    -n $DEPLOYMENT_NAMESPACE --timeout=10m &
oodd_pid=$!

set +e  # Temporarily disable exit on error to wait for both background jobs to finish
wait $primary_pid
primary_status=$?
wait $oodd_pid
oodd_status=$?
set -e  # Re-enable exit on error

if [ $primary_status -ne 0 ] || [ $oodd_status -ne 0 ]; then
    set +e  # Disable exit on error so all the diagnostic information available gets printed
    echo "Error: One or both inference deployments for detector $DETECTOR_ID failed to rollout within the timeout period."
    echo "Dumping a bunch of diagnostic information..."
    kubectl -n $DEPLOYMENT_NAMESPACE describe deployment/inferencemodel-primary-$DETECTOR_ID_WITH_DASHES
    kubectl -n $DEPLOYMENT_NAMESPACE logs deployment/inferencemodel-primary-$DETECTOR_ID_WITH_DASHES
    kubectl -n $DEPLOYMENT_NAMESPACE describe deployment/inferencemodel-oodd-$DETECTOR_ID_WITH_DASHES
    kubectl -n $DEPLOYMENT_NAMESPACE logs deployment/inferencemodel-oodd-$DETECTOR_ID_WITH_DASHES
    exit 1
fi

echo "Inference deployment for detector $DETECTOR_ID has successfully rolled out."

echo "Running the Helm tests..."

helm test -n default ${HELM_RELEASE_NAME} --hide-notes

echo "Helm tests completed successfully."

export EDGE_SETUP=1

./test/integration/run_tests.sh

# cleanup
echo "Deleting helm deployment..."
helm uninstall ${HELM_RELEASE_NAME} -n default

echo "Waiting for namespace $DEPLOYMENT_NAMESPACE to terminate..."
if ! kubectl wait --for=delete namespace/$DEPLOYMENT_NAMESPACE --timeout=5m; then
    echo "Error: namespace $DEPLOYMENT_NAMESPACE failed to terminate within the timeout period."
    exit 1
fi

echo "Namespace $DEPLOYMENT_NAMESPACE has been successfully deleted."
echo "Test completed successfully."

