#!/bin/bash

K=${KUBECTL_CMD:-"kubectl"}
DEPLOYMENT_NAMESPACE=${DEPLOYMENT_NAMESPACE:-$($K config view -o json | jq -r '.contexts[] | select(.name == "'$($K config current-context)'") | .context.namespace // "default"')}
# Update K to include the deployment namespace
K="$K -n $DEPLOYMENT_NAMESPACE"

cd $(dirname "$0")

# Run the refresh-ecr-login.sh, telling it to use the configured KUBECTL_CMD
KUBECTL_CMD="$K" ./refresh-ecr-login.sh

# Now we try to find the AWS credentials.  Let's look in the CLI
if command -v aws >/dev/null 2>&1; then
    # Try to retrieve AWS credentials from aws configure
    AWS_ACCESS_KEY_ID_CMD=$(aws configure get aws_access_key_id 2>/dev/null)
    AWS_SECRET_ACCESS_KEY_CMD=$(aws configure get aws_secret_access_key 2>/dev/null)
fi
# Use the CLI credentials if available, otherwise use environment variables
AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID_CMD:-$AWS_ACCESS_KEY_ID}
AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY_CMD:-$AWS_SECRET_ACCESS_KEY}

# Check that we have credentials
if [ -z "$AWS_ACCESS_KEY_ID" ] || [ -z "$AWS_SECRET_ACCESS_KEY" ]; then
    fail "No AWS credentials found"
fi

# Create the secret with either retrieved or environment values
$K delete --ignore-not-found secret aws-credentials
$K create secret generic aws-credentials \
    --from-literal=aws_access_key_id=$AWS_ACCESS_KEY_ID \
    --from-literal=aws_secret_access_key=$AWS_SECRET_ACCESS_KEY

# Verify secrets have been properly created
if ! $K get secret registry-credentials; then
    # These should have been created in refresh-ecr-login.sh
    fail "registry-credentials secret not found"
fi

if ! $K get secret aws-credentials; then
    echo "aws-credentials secret not found"
fi
