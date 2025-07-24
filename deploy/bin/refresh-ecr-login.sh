#!/bin/bash

set -e

K=${KUBECTL_CMD:-"kubectl"}
# No need to explicitly pick the namespace - this normally runs in its own namespace

# ECR_REGISTRY="767397850842.dkr.ecr.us-west-2.amazonaws.com"
ECR_REGISTRY="557423365154.dkr.ecr.us-west-2.amazonaws.com"
# TODO: We should probably put this in DNS

ECR_PASSWORD=$(aws ecr get-login-password --region us-west-2)
if [ $? -ne 0 ]; then
    echo "Failed to get ECR password"
    exit 1
fi

echo "Fetched short-lived ECR credentials from AWS"

if command -v docker >/dev/null 2>&1; then
    echo $ECR_PASSWORD | docker login \
        --username AWS \
        --password-stdin  \
        $ECR_REGISTRY
else
    echo "Docker is not installed. Skipping docker ECR login."
fi

$K delete --ignore-not-found secret registry-credentials

$K create secret docker-registry registry-credentials \
    --docker-server=$ECR_REGISTRY \
    --docker-username=AWS \
    --docker-password=$ECR_PASSWORD

echo "Stored ECR credentials in secret registry-credentials"