#!/bin/sh

# Part two of getting AWS credentials set up. 
# This script runs in a kubectl container and applies the credentials to the cluster.

# We do two things:
# 1. Create a secret with an AWS credentials file. We use a file instead of environment variables
#    so that we can change it without restarting the pod.
# 2. Create a secret with a Docker registry credentials. This is used to pull images from ECR.

sleep 5  # Ensure the token is written before using it
kubectl create secret generic aws-credentials-file --from-file /shared/credentials \
    --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret docker-registry registry-credentials \
    --docker-server={{ .Values.ecrRegistry }} \
    --docker-username=AWS \
    --docker-password="$(cat /shared/token.txt)" \
    --dry-run=client -o yaml | kubectl apply -f -
