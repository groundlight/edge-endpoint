#!/bin/bash

set -ex 

# Ensure that you're in the same directory as this script before running it
cd "$(dirname "$0")"

pwd

TAG=$(../deploy/bin/git-tag-name.sh)
SQLITE_DB_IMAGE="edge-sqlite-db"
ECR_URL="723181461334.dkr.ecr.us-west-2.amazonaws.com"

# Authenticate docker to ECR
aws ecr get-login-password --region us-west-2 | docker login \
                  --username AWS \
                  --password-stdin  ${ECR_URL}

# Check if the first argument is "dev". If it is, only build the image for the current
# platform 
if [ "$1" == "dev" ]; then
  docker build --tag ${SQLITE_DB_IMAGE} .
  docker tag ${SQLITE_DB_IMAGE}:latest ${ECR_URL}/${SQLITE_DB_IMAGE}:${TAG} 
  docker push ${ECR_URL}/${SQLITE_DB_IMAGE}:${TAG}
  exit 0
fi

docker build --tag ${SQLITE_DB_IMAGE} .
docker tag ${SQLITE_DB_IMAGE}:latest ${ECR_URL}/${SQLITE_DB_IMAGE}:${TAG} 
docker push ${ECR_URL}/${SQLITE_DB_IMAGE}:${TAG}