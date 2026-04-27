#!/bin/bash

# This script deploys a k3s cluster to a Balena fleet
#
# The script will:
# - Copy the appropriate docker-compose file based on CPU/GPU/Jetson selection
# - For GPU builds, inject the balenaOS version into the compose file
# - Push the configuration to the specified Balena fleet
# - Clean up temporary files on exit
#
# Balena will ALWAYS build the `docker-compose.yml` file in the root directory (not configurable),
# and doesn't support docker-compose overrides or profiles, so we copy the right file to root.
#
# Usage:
#   ./deploy_balena.sh <fleet_name> <cpu|gpu|jetson-orin> [balena_os_version]
#
# Arguments:
#   fleet_name        The name of the Balena fleet to deploy to
#   cpu|gpu|jetson-orin  The device flavor
#   balena_os_version    (GPU only) The balenaOS version running on the device.
#                        Must match the device's OS version for kernel module compilation.
#                        Defaults to "6.0.24%2Brev1".
#
# Examples:
#   ./deploy_balena.sh my-fleet cpu
#   ./deploy_balena.sh my-fleet gpu
#   ./deploy_balena.sh my-fleet gpu "6.0.24%2Brev1"
#   ./deploy_balena.sh my-fleet jetson-orin

if [ "$#" -lt 2 ]; then
    echo "Usage: $0 <fleet_name> <cpu|gpu|jetson-orin> [balena_os_version]"
    exit 1
fi

cd "$(dirname "$0")"

FLEET_NAME=$1
FLAVOR=$(echo "$2" | tr '[:upper:]' '[:lower:]')
BALENA_OS_VERSION=${3:-"6.0.24%2Brev1"}

if [ "$FLAVOR" != "cpu" ] && [ "$FLAVOR" != "gpu" ] && [ "$FLAVOR" != "jetson-orin" ]; then
    echo "Error: Second argument must be 'cpu', 'gpu', or 'jetson-orin'"
    exit 1
fi

case "$FLAVOR" in
    "cpu")
        cp deploy/balena-k3s/resources/docker-compose-cpu.yml docker-compose.yml
        ;;
    "gpu")
        cp deploy/balena-k3s/resources/docker-compose-gpu.yml docker-compose.yml
        # Inject the balenaOS version into the compose file
        sed -i.bak "s|BALENA_OS_VERSION:.*|BALENA_OS_VERSION: \"${BALENA_OS_VERSION}\"|" docker-compose.yml
        rm -f docker-compose.yml.bak
        echo "Using balenaOS version: $BALENA_OS_VERSION"
        ;;
    "jetson-orin")
        cp deploy/balena-k3s/resources/docker-compose-jetson-orin.yml docker-compose.yml
        ;;
esac

cleanup() {
    echo "Cleaning up..."
    rm -f docker-compose.yml
}
trap cleanup EXIT

echo "Pushing to fleet: $FLEET_NAME with $FLAVOR configuration..."
balena push "$FLEET_NAME"

echo "Deployment complete!"
