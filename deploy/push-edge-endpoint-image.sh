#!/bin/bash 

set -ex


# Ensure that you're in the same directory as this script before running it
cd "$(dirname "$0")"

TAG=$(./git-tag-name.sh)

# Authenticate docker to ECR
aws ecr get-login-password --region us-west-2 | docker login --username AWS --password-stdin  723181461334.dkr.ecr.us-west-2.amazonaws.com

# Tag image
docker tag edge-endpoint:latest 723181461334.dkr.ecr.us-west-2.amazonaws.com/edge-endpoint:${TAG}

# Push image to ECR
docker push 723181461334.dkr.ecr.us-west-2.amazonaws.com/edge-endpoint:${TAG}



