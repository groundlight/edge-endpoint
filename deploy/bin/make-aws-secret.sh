#!/bin/bash

K=${KUBECTL_CMD:-"kubectl"}
DEPLOYMENT_NAMESPACE=${DEPLOYMENT_NAMESPACE:-$($K config view -o json | jq -r '.contexts[] | select(.name == "'$($K config current-context)'") | .context.namespace // "default"')}
# Update K to include the deployment namespace
K="$K -n $DEPLOYMENT_NAMESPACE"

cd $(dirname "$0")
# Make sure the initial login is in the correct namespace
KUBECTL_CMD="$K" ./refresh-ecr-login.sh

# Use configured credentials if both are available, otherwise use environment variables
AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID_CMD:-$AWS_ACCESS_KEY_ID}
AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY_CMD:-$AWS_SECRET_ACCESS_KEY}

# Create the secret with either retrieved or environment values
$K create secret generic aws-credentials \
    --from-literal=aws_access_key_id=$AWS_ACCESS_KEY_ID \
    --from-literal=aws_secret_access_key=$AWS_SECRET_ACCESS_KEY

# Verify secrets have been properly created
if ! $K get secret registry-credentials; then
    fail "registry-credentials secret not found"
fi

if ! $K get secret aws-credentials; then
    echo "aws-credentials secret not found"
fi
