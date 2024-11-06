#!/bin/bash

K=${KUBECTL_CMD:-"kubectl"}
DEPLOYMENT_NAMESPACE=${DEPLOYMENT_NAMESPACE:-$($K config view -o json | jq -r '.contexts[] | select(.name == "'$($K config current-context)'") | .context.namespace // "default"')}
# Update K to include the deployment namespace
K="$K -n $DEPLOYMENT_NAMESPACE"

if command -v docker >/dev/null 2>&1; then
    # Enable ECR login - make sure you have the aws client configured properly, or an IAM role
    # attached to your instance
    aws ecr get-login-password --region us-west-2 | docker login \
        --username AWS \
        --password-stdin  \
        767397850842.dkr.ecr.us-west-2.amazonaws.com
else
    echo "Docker is not installed. Skipping docker ECR login."
fi


# Note: needs testing
$K delete --ignore-not-found secret registry-credentials
$K delete --ignore-not-found secret aws-credentials

# NOTE: these credentials seem to be expiring, causing problems later.
PASSWORD=$(aws ecr get-login-password --region us-west-2)
$K create secret docker-registry registry-credentials \
    --docker-server=767397850842.dkr.ecr.us-west-2.amazonaws.com \
    --docker-username=AWS \
    --docker-password=$PASSWORD

# Store AWS credentials in a Kubernetes secret
if command -v aws >/dev/null 2>&1; then
    # Try to retrieve AWS credentials from aws configure
    AWS_ACCESS_KEY_ID_CMD=$(aws configure get aws_access_key_id 2>/dev/null)
    AWS_SECRET_ACCESS_KEY_CMD=$(aws configure get aws_secret_access_key 2>/dev/null)

    # Check if both keys have values
    if [ -n "$AWS_ACCESS_KEY_ID_CMD" ] && [ -n "$AWS_SECRET_ACCESS_KEY_CMD" ]; then
        $K create secret generic aws-credentials \
            --from-literal=aws_access_key_id=$AWS_ACCESS_KEY_ID_CMD \
            --from-literal=aws_secret_access_key=$AWS_SECRET_ACCESS_KEY_CMD
    else
        # Use environment variables if keys are missing in aws configure
        $K create secret generic aws-credentials \
            --from-literal=aws_access_key_id=${AWS_ACCESS_KEY_ID} \
            --from-literal=aws_secret_access_key=${AWS_SECRET_ACCESS_KEY}
    fi
else
    # Use environment variables if aws command does not exist
    $K create secret generic aws-credentials \
        --from-literal=aws_access_key_id=${AWS_ACCESS_KEY_ID} \
        --from-literal=aws_secret_access_key=${AWS_SECRET_ACCESS_KEY}
fi

# Verify secrets have been properly created
if ! $K get secret registry-credentials; then
    fail "registry-credentials secret not found"
fi

if ! $K get secret aws-credentials; then
    echo "aws-credentials secret not found"
fi
