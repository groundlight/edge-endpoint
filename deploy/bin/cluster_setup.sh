#!/bin/bash 

set -ex 

K="k3s kubectl"
INFERENCE_FLAVOR=${INFERENCE_FLAVOR:-"CPU"}

# Configmaps 
$K delete configmap --ignore-not-found edge-config 
$K delete configmap --ignore-not-found inference-deployment-template 
$K delete configmap --ignore-not-found inference-flavor || echo "No inference flavor found - this is expected"

$K create configmap edge-config --from-file=configs/edge-config.yaml
$K create configmap inference-deployment-template \
        --from-file=deploy/k3s/inference_deployment.yaml
$K create configmap inference-flavor --from-literal=inference-flavor=${INFERENCE_FLAVOR}


# Secrets 
./deploy/bin/make-gl-api-token-secret.sh
./deploy/bin/make-aws-secret.sh 

# Edge Deployment
$K delete --ignore-not-found deployment edge-endpoint
$K apply -f deploy/k3s/edge_deployment.yaml
$K describe deployment edge-endpoint