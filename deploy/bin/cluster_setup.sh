#!/bin/bash 

set -ex 

fail() {
    echo $1 
    exit 1
}

announce() {
    echo $1
}

K="k3s kubectl"
INFERENCE_FLAVOR=${INFERENCE_FLAVOR:-"CPU"}

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

# Configmaps and deployments
$K delete configmap --ignore-not-found edge-config 
$K delete configmap --ignore-not-found inference-deployment-template 

if [[ -n "{EDGE_CONFIG}" ]]; then 
    announce "Creating config from `EDGE_CONFIG` env var"
    $K create configmap edge-config --from-literal="edge-config.yaml=${EDGE_CONFIG}"
else 
    $K create configmap edge-config --from-file=configs/edge-config.yaml
fi

if [[ "$INFERENCE_FLAVOR" == "CPU" ]]; then 
    announce "Preparing inference deployments with CPU flavor"

    # Customize edge_deployment and inference_deployment_template with the CPU patch
    $K kustomize deploy/k3s/inference_deployment > inference_deployment.yaml 
    $K create configmap inference-deployment-template \
            --from-file=inference_deployment.yaml

    rm inference_deployment.yaml
else
    announce "Preparing inference deployments with GPU flavor"
    $K create configmap inference-deployment-template \
            --from-file=deploy/k3s/inference_deployment/inference_deployment_template.yaml
fi


# Edge Deployment
$K apply -f deploy/k3s/service_account.yaml 
$K delete --ignore-not-found deployment edge-endpoint

if [[ "$INFERENCE_FLAVOR" == "CPU" ]]; then
    $K kustomize deploy/k3s/edge_deployment > edge_deployment.yaml
    $K apply -f edge_deployment.yaml
    rm edge_deployment.yaml
else
    $K apply -f deploy/k3s/edge_deployment/edge_deployment.yaml 
fi

$K describe deployment edge-endpoint