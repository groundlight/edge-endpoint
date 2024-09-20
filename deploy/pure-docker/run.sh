#!/bin/bash

docker run --name myk3s \
           -v ${HOME}/tmp/edge-config.yaml:/opt/groundlight/configs/edge-config.yaml \
           -v ${HOME}/.aws/credentials:/root/.aws/credentials \
           -e AWS_PROFILE=readers \
           -e AWS_DEFAULT_REGION=us-west-2 \
           -e GROUNDLIGHT_API_TOKEN=${GROUNDLIGHT_API_TOKEN} \
           -e INFERENCE_FLAVOR=CPU \
           -p 7443:6443 \
           -p 30101:30101 \
           --privileged \
           --detach \
           k3s-container