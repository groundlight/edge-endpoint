#!/bin/bash

# How to use this script:
# ./deploy/bin/cluster_setup.sh [db_reset]
#
# The optional argument "db_reset" will delete all the data in the database.
# For now, this means all
# - detectors in the `inference_deployments` table
# - image queries in the `image_queries_edge` table
# For more on these tables you can examine the database file at
# /opt/groundlight/edge/sqlite/sqlite.db on the attached EFS volume. 

# Possible env vars:
# - KUBECTL_CMD: path to kubectl command. Defaults to "kubectl" but can be set to "k3s kubectl" if using k3s
# - INFERENCE_FLAVOR: "CPU" or "GPU". Defaults to "GPU"
# - EDGE_CONFIG: contents of edge-config.yaml. If not set, will use configs/edge-config.yaml
# - EFS_VOLUME_ID: ID of the EFS volume to use if the PV and PVC don't exist yet. 


# move to the root directory of the repo
cd "$(dirname "$0")"/../..

set -ex

fail() {
    echo $1
    exit 1
}


K=${KUBECTL_CMD:-kubectl}
INFERENCE_FLAVOR=${INFERENCE_FLAVOR:-"GPU"}
DB_RESTART=$1

# Ensure database file has been correctly setup. If the first argument is "db_reset",
# all the data in the database will be deleted first. 
# For now, this means all 
# - detectors in the `inference_deployments` table
# - image queries in the `image_queries_edge` table
# For more on these tables you can examine the database file at
# /opt/groundlight/edge/sqlite/sqlite.db 
./deploy/bin/setup_db.sh $DB_RESTART

# Secrets
./deploy/bin/make-aws-secret.sh

# Verify secrets have been properly created
if ! $K get secret registry-credentials; then
    fail "registry-credentials secret not found"
fi


# Configmaps and deployments
$K delete configmap --ignore-not-found edge-config
$K delete configmap --ignore-not-found inference-deployment-template
$K delete configmap --ignore-not-found kubernetes-namespace

if [[ -n "${EDGE_CONFIG}" ]]; then
    echo "Creating config from EDGE_CONFIG env var"
    $K create configmap edge-config --from-literal="edge-config.yaml=${EDGE_CONFIG}"
else
    echo "Creating config from configs/edeg-config.yaml"
    $K create configmap edge-config --from-file=configs/edge-config.yaml
fi

if [[ "${INFERENCE_FLAVOR}" == "CPU" ]]; then
    echo "Preparing inference deployments with CPU flavor"

    # Customize inference_deployment_template with the CPU patch
    $K kustomize deploy/k3s/inference_deployment > inference_deployment_template.yaml
    $K create configmap inference-deployment-template \
            --from-file=inference_deployment_template.yaml
    rm inference_deployment_template.yaml
else
    echo "Preparing inference deployments with GPU flavor"
    $K create configmap inference-deployment-template \
            --from-file=deploy/k3s/inference_deployment/inference_deployment_template.yaml
fi

# Create a configmap corresponding to the namespace we are deploying to
DEPLOYMENT_NAMESPACE=$($K config view -o json | jq -r '.contexts[] | select(.name == "'$(kubectl config current-context)'") | .context.namespace')
$K create configmap kubernetes-namespace --from-literal=namespace=${DEPLOYMENT_NAMESPACE}

# Clean up existing deployments and services (if they exist)
$K delete --ignore-not-found deployment edge-endpoint
$K delete --ignore-not-found service edge-endpoint-service
$K get deployments -o custom-columns=":metadata.name" --no-headers=true | \
    grep "inferencemodel" | \
    xargs -I {} $K delete deployments {}
$K get service -o custom-columns=":metadata.name" --no-headers=true | \
    grep "inference-service" | \
    xargs -I {} $K delete service {}

# Reapply changes

# Check if the edge-endpoint-pvc exists. If not, create it
if ! $K get pvc edge-endpoint-pvc; then
    # If environment variable EFS_VOLUME_ID is not set, exit 
    if [[ -z "${EFS_VOLUME_ID}" ]]; then
        fail "EFS_VOLUME_ID environment variable not set"
    fi
    # Use envsubst to replace the EFS_VOLUME_ID in the persistentvolumeclaim.yaml template
    envsubst < deploy/k3s/persistentvolumeclaim.yaml > deploy/k3s/persistentvolumeclaim.yaml.tmp
    $K apply -f deploy/k3s/persistentvolumeclaim.yaml.tmp
fi

$K apply -f deploy/k3s/service_account.yaml
$K apply -f deploy/k3s/edge_deployment/edge_deployment.yaml

$K describe deployment edge-endpoint