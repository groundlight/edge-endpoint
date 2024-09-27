#!/bin/bash

set -ex

K="k3s kubectl"

# Update system
sudo apt update && sudo apt upgrade -y


# Install k3s
echo "Installing k3s..."
curl -sfL https://get.k3s.io |  K3S_KUBECONFIG_MODE="644" sh -s - --disable=traefik

check_k3s_is_running() {
    local TIMEOUT=30 # Maximum wait time of 30 seconds
    local COUNT=0

    while [ $COUNT -lt $TIMEOUT ]; do
        if sudo $K get node >/dev/null 2>&1; then
            echo "k3s installed sucessfully."
            return 0
        fi
        sleep 1
        COUNT=$((COUNT+1))
    done
    echo "k3s did not start or respond within the expected time."
    return 1
}

if check_k3s_is_running; then
    echo "kubectl has been configured for the current user."
else
    echo "There was an issue with the K3s installation. Please check the system logs."
    exit 0
fi

# Set up kubeconfig for the current user
mkdir -p ~/.kube
cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
chmod 600 ~/.kube/config