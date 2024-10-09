#!/bin/bash

# How to use this script:
# ./deploy/bin/cluster_setup.sh [db_reset]
#
# The optional argument "db_reset" will delete all the data in the database.
# For now, this means all
# - detectors in the `inference_deployments` table
# - image queries in the `image_queries_edge` table
# For more on these tables you can examine the database file at
# /opt/groundlight/edge/sqlite/sqlite.db on the attached volume (EFS/local).

# Possible env vars:
# - KUBECTL_CMD: path to kubectl command. Defaults to "kubectl" but can be set to "k3s kubectl" if using k3s
# - INFERENCE_FLAVOR: "CPU" or "GPU". Defaults to "GPU"
# - EDGE_CONFIG: contents of edge-config.yaml. If not set, will use configs/edge-config.yaml
# - DEPLOY_LOCAL_VERSION: Indicates whether we are building the local version of the edge endpoint.
#           If set to 0, we will attach an EFS instead of a local volume. Defaults to 1.
# - EFS_VOLUME_ID: ID of the EFS volume to use if we are using the EFS version.
# - DEPLOYMENT_NAMESPACE: Namespace to deploy to. Defaults to the current namespace.
# - RUN_EDGE_ENDPOINT: Indicates whether or not to launch the edge endpoint pods.
#           If set, launch edge-endpoint pods. If not set, do not launch pods.

set -ex

fail() {
    echo $1
    exit 1
}

# Function to check for conflicting PV.
# This is a robustness measure to guard against errors when a user tries to create a
# persistent volume with hostPath when we already have an EFS volume mounted or vice versa.
check_pv_conflict() {
    local pv_name=$1
    local expected_storage_class=$2

    # Get existing PV details if it exists
    pv_detail=$(kubectl get pv "$pv_name" -o json 2>/dev/null)
    if [[ -z "$pv_detail" ]]; then
        # PV does not exist, no conflict
        return 0
    fi

    # Extract storage class and host path from existing PV
    existing_storage_class=$(echo "$pv_detail" | jq -r '.spec.storageClassName')

    # Compare existing PV details with expected details
    if [[ "$existing_storage_class" != "$expected_storage_class" ]]; then
        echo "Alert: Existing PersistentVolume '$pv_name' conflicts with the anticipated resource."
        echo "Existing storage class: $existing_storage_class, Expected: $expected_storage_class"
        echo "Consider deleting the existing PV/PVC and try again."
        return 1
    fi
    return 0
}

if [ -n "$BALENA" ] && [ -z "$RUN_EDGE_ENDPOINT" ]; then
    echo "Using Balena and RUN_EDGE_ENDPOINT is unset. Now exiting pod creation."
    exit 0
fi

echo "RUN_EDGE_ENDPOINT is set to '${RUN_EDGE_ENDPOINT}'. Starting edge endpoint."

K=${KUBECTL_CMD:-"kubectl"}
INFERENCE_FLAVOR=${INFERENCE_FLAVOR:-"GPU"}
DB_RESET=$1
DEPLOY_LOCAL_VERSION=${DEPLOY_LOCAL_VERSION:-1}
DEPLOYMENT_NAMESPACE=${DEPLOYMENT_NAMESPACE:-$($K config view -o json | jq -r '.contexts[] | select(.name == "'$($K config current-context)'") | .context.namespace // "default"')}

# Update K to include the deployment namespace
K="$K -n $DEPLOYMENT_NAMESPACE"

# move to the root directory of the repo
cd "$(dirname "$0")"/../..

# Create Secrets
if ! ./deploy/bin/make-aws-secret.sh; then
    echo "Failed to execute make-aws-secret.sh successfully. Exiting."
    exit 1
fi

# Configmaps, secrets, and deployments
$K delete configmap --ignore-not-found edge-config -n ${DEPLOYMENT_NAMESPACE}
$K delete configmap --ignore-not-found inference-deployment-template -n ${DEPLOYMENT_NAMESPACE}
$K delete configmap --ignore-not-found kubernetes-namespace -n ${DEPLOYMENT_NAMESPACE}
$K delete configmap --ignore-not-found setup-db -n ${DEPLOYMENT_NAMESPACE}
$K delete configmap --ignore-not-found db-reset -n ${DEPLOYMENT_NAMESPACE}
$K delete secret --ignore-not-found groundlight-api-token -n ${DEPLOYMENT_NAMESPACE}

set +x  # temporarily disable command echoing to avoid printing secrets
if [[ -n "${GROUNDLIGHT_API_TOKEN}" ]]; then
    echo "Creating groundlight-api-token secret"
    $K create secret generic groundlight-api-token --from-literal=GROUNDLIGHT_API_TOKEN=${GROUNDLIGHT_API_TOKEN} -n ${DEPLOYMENT_NAMESPACE}
fi
set -x  # re-enable command echoing

if [[ -n "${EDGE_CONFIG}" ]]; then
    echo "Creating config from EDGE_CONFIG env var"
    $K create configmap edge-config --from-literal="edge-config.yaml=${EDGE_CONFIG}"
else
    echo "Creating config from configs/edge-config.yaml"
    $K create configmap edge-config --from-file=configs/edge-config.yaml
fi

if [[ "${INFERENCE_FLAVOR}" == "CPU" ]]; then
    echo "Preparing inference deployments with CPU flavor"

    # Customize inference_deployment_template with the CPU patch
    $K kustomize deploy/k3s/inference_deployment > temp_inference_deployment_template.yaml
    $K create configmap inference-deployment-template \
            --from-file=inference_deployment_template.yaml=temp_inference_deployment_template.yaml
    rm temp_inference_deployment_template.yaml
else
    echo "Preparing inference deployments with GPU flavor"
    $K create configmap inference-deployment-template \
            --from-file=deploy/k3s/inference_deployment/inference_deployment_template.yaml
fi

# Create a configmap corresponding to the namespace we are deploying to
$K create configmap kubernetes-namespace --from-literal=namespace=${DEPLOYMENT_NAMESPACE}

$K create configmap setup-db --from-file=$(pwd)/deploy/bin/setup_db.sh -n ${DEPLOYMENT_NAMESPACE}

# If db_reset is passed as an argument, create a environment variable DB_RESET
if [[ "$DB_RESET" == "db_reset" ]]; then
    $K create configmap db-reset --from-literal=DB_RESET=1
else
    $K create configmap db-reset --from-literal=DB_RESET=0
fi

# Clean up existing deployments and services (if they exist)
$K delete --ignore-not-found deployment edge-endpoint
$K delete --ignore-not-found service edge-endpoint-service
$K delete --ignore-not-found deployment warmup-inference-model
$K get deployments -o custom-columns=":metadata.name" --no-headers=true | \
    grep "inferencemodel" | \
    xargs -I {} $K delete deployments {}
$K get service -o custom-columns=":metadata.name" --no-headers=true | \
    grep "inference-service" | \
    xargs -I {} $K delete service {}

# Reapply changes

# Check if DEPLOY_LOCAL_VERSION is set. If so, use a local volume instead of an EFS volume
if [[ "${DEPLOY_LOCAL_VERSION}" == "1" ]]; then
    if ! check_pv_conflict "edge-endpoint-pv" "local-sc"; then
        fail "PersistentVolume edge-endpoint-pv conflicts with the existing resource."
    fi

    $K apply -f deploy/k3s/local_persistent_volume.yaml
else
    # If environment variable EFS_VOLUME_ID is not set, exit
    if [[ -z "${EFS_VOLUME_ID}" ]]; then
        fail "EFS_VOLUME_ID environment variable not set"
    fi

    if ! check_pv_conflict "edge-endpoint-pv" "efs-sc"; then
        fail "PersistentVolume edge-endpoint-pv conflicts with the existing resource."
    fi

    # Use envsubst to replace the EFS_VOLUME_ID in the persistentvolumeclaim.yaml template
    envsubst < deploy/k3s/efs_persistent_volume.yaml > deploy/k3s/persistentvolume.yaml
    $K apply -f deploy/k3s/persistentvolume.yaml
    rm deploy/k3s/persistentvolume.yaml
fi

# Check if the edge-endpoint-pvc exists. If not, create it
if ! $K get pvc edge-endpoint-pvc; then
    # If environment variable EFS_VOLUME_ID is not set, exit
    if [[ -z "${EFS_VOLUME_ID}" ]]; then
        fail "EFS_VOLUME_ID environment variable not set"
    fi
    # Use envsubst to replace the EFS_VOLUME_ID in the persistentvolumeclaim.yaml template
    envsubst < deploy/k3s/persistentvolume.yaml > deploy/k3s/persistentvolume.yaml.tmp
    $K apply -f deploy/k3s/persistentvolume.yaml.tmp
    rm deploy/k3s/persistentvolume.yaml.tmp
fi

# Make pinamod directory for hostmapped volume
sudo mkdir -p /opt/groundlight/edge/pinamod-public

# Substitutes the namespace in the service_account.yaml template
envsubst < deploy/k3s/service_account.yaml > deploy/k3s/service_account.yaml.tmp
$K apply -f deploy/k3s/service_account.yaml.tmp
rm deploy/k3s/service_account.yaml.tmp

$K apply -f deploy/k3s/inference_deployment/warmup_inference_model.yaml
$K apply -f deploy/k3s/edge_deployment/edge_deployment.yaml

$K describe deployment edge-endpoint