#!/bin/bash

# move to the root directory of the repo
cd "$(dirname "$0")"/../..

set -ex

fail() {
    echo $1
    exit 1
}

K="k3s kubectl"
INFERENCE_FLAVOR=${INFERENCE_FLAVOR:-"GPU"}

# Secrets
# ./deploy/bin/make-gl-api-token-secret.sh
./deploy/bin/make-aws-secret.sh

# Verify secrets have been properly created
if ! $K get secret registry-credentials; then
    fail "registry-credentials secret not found"
fi

# if ! $K get secret groundlight-secrets; then
#     fail "groundlight-secrets secret not found"
# fi

# Configmaps and deployments
$K delete configmap --ignore-not-found edge-config
$K delete configmap --ignore-not-found inference-deployment-template

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

# Clean up existing deployments and services (if they exist)
$K apply -f deploy/k3s/service_account.yaml
$K delete --ignore-not-found deployment edge-endpoint
$K delete --ignore-not-found service edge-endpoint-service
$K get deployments -o custom-columns=":metadata.name" --no-headers=true | \
    grep "inferencemodel" | \
    xargs -I {} $K delete deployments {}
$K get service -o custom-columns=":metadata.name" --no-headers=true | \
    grep "inference-service" | \
    xargs -I {} $K delete service {}

# Reapply changes
$K apply -f deploy/k3s/edge_deployment/edge_deployment.yaml

$K describe deployment edge-endpoint