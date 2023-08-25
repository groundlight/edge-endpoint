#!/bin/bash 

# Create a kubernetes secret for the groundlight api token
# Make sure that you have the groundlight api token set in your environment

kubectl create secret generic groundlight-secrets \
    --from-literal=api-token=${GROUNDLIGHT_API_TOKEN}