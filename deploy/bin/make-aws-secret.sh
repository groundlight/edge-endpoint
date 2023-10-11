#!/bin/bash

K="k3s kubectl"

if command -v docker >/dev/null 2>&1; then
    # Enable ECR login - make sure you have the aws client configured properly, or an IAM role
    # attached to your instance
    aws ecr get-login-password --region us-west-2 | docker login \
        --username AWS \
        --password-stdin  \
        723181461334.dkr.ecr.us-west-2.amazonaws.com
else
    echo "Docker is not installed. Skipping docker ECR login."
fi


# Create an AWS secret for the edge-endpoint to properly pull images from ECR
# Note: needs testing
$K delete --ignore-not-found secret registry-credentials

PASSWORD=$(aws ecr get-login-password --region us-west-2)
$K create secret docker-registry registry-credentials \
    --docker-server=723181461334.dkr.ecr.us-west-2.amazonaws.com \
    --docker-username=AWS \
    --docker-password=$PASSWORD
