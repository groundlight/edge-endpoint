#!/bin/bash

# This script deploys a k3s cluster to a Balena fleet
#
# The script will:
# - Copy the appropriate docker-compose file based on CPU/GPU selection
# - Push the configuration to the specified Balena fleet
# - Clean up temporary files on exit
#
# This is necessary because
# a) If we don't have a GPU, we don't want to deploy the `gpu` container (which will fail and is a dependency of `server`)
# b) Balena will ALWAYS build the `docker-compose.yml` file in the root directory (not configurable)
# c) Balena doesn't support docker-compose overrides or profiles, so we can't use a single file neatly
#
# The script takes two arguments:
# 1. fleet_name: The name of the Balena fleet to deploy to
# 2. cpu|gpu: Whether to deploy with CPU-only or GPU support
#
# Examples:
#   ./deploy_balena.sh my-fleet cpu    # Deploy to a fleet of CPU-only devices
#   ./deploy_balena.sh my-fleet gpu    # Deploy to a fleet of GPU devices w/ NVIDIA drivers and GPU operator
#   ./deploy_balena.sh my-fleet jetson    # Deploy to a fleet of Jetson devices w/ Jetpack and GPU operator


if [ "$#" -lt 2 ]; then
    echo "Usage: $0 <fleet_name> <cpu|gpu|jetson>"
    exit 1
fi

cd "$(dirname "$0")"

FLEET_NAME=$1
FLAVOR=$(echo "$2" | tr '[:upper:]' '[:lower:]')

if [ "$FLAVOR" != "cpu" ] && [ "$FLAVOR" != "gpu" ] && [ "$FLAVOR" != "jetson" ]; then
    echo "Error: Second argument must be 'cpu', 'gpu', or 'jetson'"
    exit 1
fi

# Copy the appropriate compose file
case "$FLAVOR" in
    "cpu")
        cp deploy/balena-k3s/resources/docker-compose-cpu.yml docker-compose.yml
        ;;
    "gpu")
        cp deploy/balena-k3s/resources/docker-compose-gpu.yml docker-compose.yml
        ;;
    "jetson")
        cp deploy/balena-k3s/resources/docker-compose-jetson.yml docker-compose.yml
        ;;
    *)
        echo "Error: Second argument must be 'cpu', 'gpu', or 'jetson'"
        exit 1
        ;;
esac

cleanup() {
    echo "Cleaning up..."
    rm -f docker-compose.yml
}
trap cleanup EXIT

# Push to balena
echo "Pushing to fleet: $FLEET_NAME with $FLAVOR configuration..."
balena push "$FLEET_NAME"

echo "Deployment complete!"