#!/bin/bash 

set -ex 

fail() {
    echo $1 
    exit 1
}

K="k3s kubectl"
INFERENCE_FLAVOR=${INFERENCE_FLAVOR:-"CPU"}

# Configmaps 
$K delete configmap --ignore-not-found edge-config 
$K delete configmap --ignore-not-found inference-deployment-template 
$K delete configmap --ignore-not-found inference-flavor || echo "No inference flavor found - this is expected"

if [[ -n "{EDGE_CONFIG}" ]]; then 
    echo "Creating config from EDGE_CONFIG env var"
    $K create configmap edge-config --from-literal=edge-config=${EDGE_CONFIG}
else 
    $K create configmap edge-config --from-file=configs/edge-config.yaml
fi
$K create configmap inference-deployment-template \
        --from-file=deploy/k3s/inference_deployment.yaml
$K create configmap inference-flavor --from-literal=inference-flavor=${INFERENCE_FLAVOR}


# Secrets 
./deploy/bin/make-gl-api-token-secret.sh
./deploy/bin/make-aws-secret.sh 

# Verify secrets have been properly created
if ! $K get secret registry-credentials; then 
    fail "registry-credentials secret not found"
fi

if ! $K get secret groundlight-secrets; then 
    fail "groundlight-secrets secret not found"
fi

# Edge Deployment
$K delete --ignore-not-found deployment edge-endpoint
$K apply -f deploy/k3s/service_account.yaml 
$K apply -f deploy/k3s/edge_deployment.yaml
$K describe deployment edge-endpoint