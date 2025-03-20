#!/bin/bash

set -e

cd "$(dirname "$0")"

ECR_ACCOUNT=${ECR_ACCOUNT:-767397850842}
ECR_REGION=${ECR_REGION:-us-west-2}
TAG=dev # In local mode, we always use the 'dev' tag
EDGE_ENDPOINT_IMAGE=${EDGE_ENDPOINT_IMAGE:-edge-endpoint}  # v0.2.0 (fastapi inference server) compatible images
ECR_URL="${ECR_ACCOUNT}.dkr.ecr.${ECR_REGION}.amazonaws.com"

# The socket that's used by the k3s containerd
SOCK=/run/k3s/containerd/containerd.sock

project_root="$(readlink -f "../../")"

build_and_upload() {
    local name=$1
    local path=. # Edge endpoint is built from the root directory
    echo "Building and uploading ${name}..."
    cd "${project_root}/${path}"
    local full_name=${ECR_URL}/${name}:${TAG}
    docker build -t ${full_name} .
    local id=$(docker image inspect ${full_name} | jq -r '.[0].Id')
    local on_server=$(sudo crictl images -q | grep $id)
    if [ -z "$on_server" ]; then
        echo "Image not found in k3s, uploading..."
        docker save ${full_name} | sudo ctr -a ${SOCK} -n k8s.io images import -
    else
        echo "Image exists in k3s, skipping upload."
    fi
}

build_and_upload "${EDGE_ENDPOINT_IMAGE}"
