#!/bin/bash 


# Enable ECR login - make sure you have the aws client configured properly, or an IAM role 
# attached to your instance
aws ecr get-login-password --region us-west-2 | docker login \
    --username AWS \
    --password-stdin  \
    723181461334.dkr.ecr.us-west-2.amazonaws.com


# Create an AWS secret for the edge-endpoint to properly pull images from ECR
# Note: needs testing 
kubectl delete --ignore-not-found secret regcred 

echo "Enter your groundlight email address: "
read EMAIL 
PASSWORD=$(aws ecr get-login-password --region us-west-2)
kubectl create secret docker-registry registry-credentials \
    --docker-server=723181461334.dkr.ecr.us-west-2.amazonaws.com \
    --docker-username=AWS \
    --docker-password=$PASSWORD \
    --docker-email=$EMAIL