#!/bin/bash

K="k3s kubectl"

$K delete --ignore-not-found secret groundlight-secrets

# Create a kubernetes secret for the groundlight api token
# Make sure that you have the groundlight api token set in your environment

$K create secret generic groundlight-secrets \
    --from-literal=api-token=${GROUNDLIGHT_API_TOKEN}