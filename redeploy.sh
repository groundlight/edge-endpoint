#!/bin/bash

# Uninstall the Helm release
echo "Uninstalling edge-endpoint-corey..."
helm uninstall edge-endpoint-corey

# Wait for the namespace to be deleted
echo "Waiting for namespace corey-edge to be deleted..."
while kubectl get namespace corey-edge &> /dev/null; do
    echo "Namespace corey-edge still exists, waiting..."
    sleep 2
done

echo "Namespace corey-edge has been deleted."

# Install the Helm release
echo "Installing edge-endpoint-corey..."
make helm-local HELM_RELEASE_NAME="edge-endpoint-corey" HELM_ARGS="-f configs/values.local.yaml --set-file configFile=configs/edge-config.yaml"

echo "Done!"