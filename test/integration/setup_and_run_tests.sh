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

# First create a detector to use for testing:
export DETECTOR_ID=$(poetry run python test/integration/integration_test.py --mode create_detector)
echo 'created detector with id:'
echo $DETECTOR_ID
# set some other environment variables
export PERSISTENT_VOLUME_NAME="test-with-k3s-pv"
export EDGE_ENDPOINT_PORT="30107"
export INFERENCE_FLAVOR="CPU"
export LIVE_TEST_ENDPOINT="http://localhost:$EDGE_ENDPOINT_PORT"

# update the config for this detector, such that we always take edge answers
# but first, save the template to a temporary file
cp configs/edge-config.yaml configs/edge-config.yaml.tmp
sed -i "s/detector_id: \"\"/detector_id: \"$DETECTOR_ID\"/" configs/edge-config.yaml
sed -i 's/edge_inference_config: "default"/edge_inference_config: "edge_answers_with_escalation"/' configs/edge-config.yaml


# # now we should delete the persistent volume before, in case it's in a bad state
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
export IMAGE_TAG=$(./deploy/bin/git-tag-name.sh)
./deploy/bin/build-push-edge-endpoint-image.sh dev
./deploy/bin/setup-ee.sh

echo "Waiting for edge-endpoint pods to rollout..."

if ! kubectl rollout status deployment/edge-endpoint -n $DEPLOYMENT_NAMESPACE --timeout=5m; then
    echo "Error: edge-endpoint pods failed to rollout within the timeout period."
    exit 1
fi

echo "Edge-endpoint pods have successfully rolled out."

echo "Waiting for the inference deployment to rollout (inferencemodel-$DETECTOR_ID)..."

DETECTOR_ID_WITH_DASHES=$(echo ${DETECTOR_ID//_/-} | tr '[:upper:]' '[:lower:]')
if ! kubectl rollout status deployment/inferencemodel-$DETECTOR_ID_WITH_DASHES -n $DEPLOYMENT_NAMESPACE --timeout=5m; then
    echo "Error: inference deployment for detector $DETECTOR_ID_WITH_DASHES failed to rollout within the timeout period."
    exit 1
fi
echo "Inference deployment for detector $DETECTOR_ID has successfully rolled out."

# restore config file
mv configs/edge-config.yaml.tmp configs/edge-config.yaml

./test/integration/run_tests.sh
