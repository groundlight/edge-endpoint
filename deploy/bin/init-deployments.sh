#!/bin/bash 

set -ex 

# Check if yq is installed
if ! command -v yq &> /dev/null; then
    echo "yq could not be found, installing..."
    
    sudo wget https://github.com/mikefarah/yq/releases/download/v4.9.8/yq_linux_amd64 -O /usr/bin/yq
    sudo chmod +x /usr/bin/yq
fi

# Parse the detector IDs from edge-config.yaml
detector_ids=$(yq eval '.motion_detection[].detector_id' configs/edge.yaml | tr '_' '-' | tr 'A-Z' 'a-z')

# Read the deployment template
template=$(<deploy/k3s/edge_deployment.yaml)

# Generate deployment for each detector_id and apply directly
for detector_id in $detector_ids; do
    # Replace placeholder with detector_id
    deployment_yaml=$(echo "$template" | sed "s/{{ DETECTOR_ID }}/$detector_id/g")
    
    echo "$deployment_yaml" | k3s kubectl apply -f -
done
