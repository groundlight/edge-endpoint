#!/bin/bash

# This script will setup the k3s testing environment. Once you've run them you can run the
# live tests, which will hit the API service that got setup
# Altogether, you can run everything with:
# > make test-with-k3s-setup-ee

# PREREQUISITE: This test must be run after you've pushed a container to ECR with
# the git tag name. This is done in the pipeline, but if you're running locally you can
# do it with:
# > ./deploy/bin/build-push-edge-endpoint-image.sh

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
export PERSISTENT_VOLUME_NAME="test-with-k3s-pv"
export EDGE_ENDPOINT_PORT="30108"
export INFERENCE_FLAVOR="CPU"
export LIVE_TEST_ENDPOINT="http://localhost:$EDGE_ENDPOINT_PORT"
export REFRESH_RATE=10 # not actually different than the default, but we may want to tweak this

# Compute the image tag name before we muck with the config file so we get
# the tag that will correspond to the current commit so it can match the image
# that was built and pushed to ECR
export IMAGE_TAG=$(./deploy/bin/git-tag-name.sh)

# update the config for this detector, such that we always take edge answers
# but first, save the template to a temporary file
cp configs/edge-config.yaml configs/edge-config.yaml.tmp
sed -i "s/detector_id: \"\"/detector_id: \"$DETECTOR_ID\"/" configs/edge-config.yaml
sed -i "s/refresh_rate: 60/refresh_rate: $REFRESH_RATE/" configs/edge-config.yaml

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


# Set up k3s with our image tag
./deploy/bin/setup-ee.sh
# restore config file
mv configs/edge-config.yaml.tmp configs/edge-config.yaml
echo "Waiting for edge-endpoint pods to rollout..."

if ! kubectl rollout status deployment/edge-endpoint -n $DEPLOYMENT_NAMESPACE --timeout=5m; then
    echo "Error: edge-endpoint pods failed to rollout within the timeout period."
    exit 1
fi

echo "Edge-endpoint pods have successfully rolled out."

echo "Waiting for the inference deployment to rollout (inferencemodel-primary-$DETECTOR_ID) and (inferencemodel-oodd-$DETECTOR_ID)..."

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

export EDGE_SETUP=1

./test/integration/run_tests.sh

