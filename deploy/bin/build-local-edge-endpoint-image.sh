#!/bin/bash

# This script will build the edge-endpoint image and add it to the local k3s cluster
# for development and testing. If the image already exists in the k3s cluster, it will
# skip the upload step.
#
# It creates a single-platform image with the full ECR-style name, but it always uses 
# the 'dev' tag. When deploying application to your local test k3s cluster, add the
# following Helm values:
# `--set edgeEndpointTag=dev --set imagePullPolicy=Never` (or add them to your values.yaml file)

# This works by:
# 1. Building the image with the local Docker daemon
# 2. Checking the image SHA in the local Docker daemon and in k3s
# 3. If they are the same, exit successfully
# 4. If they are different, export the image to stdout (it's a compressed tarball)
#    and pipe it to import it into k3s using the containerd CLI connectied to k3s's
#    containerd.
# The last step is kind of slow.
#
# Note than when you use the image in your Kubernetes app, you need to set
# imagePullPolicy=Never so K8s doesn't try to pull the image from ECR.

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
