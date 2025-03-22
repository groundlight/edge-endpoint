#!/bin/sh

# Part two of getting AWS credentials set up. 
# This script runs in a minimal container with just kubectl, and applies the credentials to the cluster.

# We do two things:
# 1. Create a secret with an AWS credentials file. We use a file instead of environment variables
#    so that we can change it without restarting the pod.
# 2. Create a secret with a Docker registry credentials. This is used to pull images from ECR.

# We wait for the credentials to be written to the shared volume by the previous script.
TIMEOUT=60  # Maximum time to wait in seconds
FILE="/shared/done"

echo "Waiting up to $TIMEOUT seconds for $FILE to exist..."

i=0
while [ $i -lt $TIMEOUT ]; do
    if [ -f "$FILE" ]; then
        echo "✅ File $FILE found! Continuing..."
        break
    fi
    sleep 1
    i=$((i + 1))
done

# If the loop completed without breaking, the file did not appear
if [ ! -f "$FILE" ]; then
    echo "❌ Error: File $FILE did not appear within $TIMEOUT seconds." >&2
    exit 1
fi


echo "Creating Kubernetes secrets..."

kubectl create secret generic aws-credentials-file --from-file /shared/credentials \
    --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret docker-registry registry-credentials \
    --docker-server={{ .Values.ecrRegistry }} \
    --docker-username=AWS \
    --docker-password="$(cat /shared/token.txt)" \
    --dry-run=client -o yaml | kubectl apply -f -
