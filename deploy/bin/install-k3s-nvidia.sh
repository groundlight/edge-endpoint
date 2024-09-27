#!/bin/bash

# Install k3s and configure GPU support
# Tested on an AWS EC2 G4 instance using the following AMI:
# Deep Learning OSS Nvidia Driver AMI GPU PyTorch 2.3.0 (Ubuntu 20.04) 20240825

# This guide was more helpful than others fwiw:
# https://support.tools/post/nvidia-gpus-on-k3s/

set -ex

check_nvidia_drivers_and_container_runtime() {
  # Retrieve existing version or default to 525
  NVIDIA_VERSION=$(modinfo nvidia 2>/dev/null | awk '/^version:/ {split($2, a, "."); print a[1]}')
  NVIDIA_VERSION=${NVIDIA_VERSION:-525}

  if ! command -v nvidia-smi &> /dev/null; then
    echo "NVIDIA drivers are not installed (nvidia-smi not found). Installing..."
    sudo apt update && sudo apt install -y "nvidia-headless-$NVIDIA_VERSION-server"
  else
    echo "NVIDIA drivers for version $NVIDIA_VERSION are installed."
  fi

  # Check if nvidia container runtime is already installed.
  if ! command -v nvidia-container-runtime &> /dev/null; then
    echo " NVIDIA container runtime is not installed. Installing..."
    # Get distribution information
    DISTRIBUTION=$(. /etc/os-release; echo "$ID$VERSION_ID")

    # Add NVIDIA Docker repository
    echo "Adding NVIDIA Docker repository..."
    curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
    curl -s -L "https://nvidia.github.io/nvidia-docker/$DISTRIBUTION/nvidia-docker.list" | sudo tee /etc/apt/sources.list.d/nvidia-docker.list

    sudo apt update -y && sudo apt install -y nvidia-container-runtime
  else
    echo " NVIDIA container runtime is installed."
  fi
}

# Install Helm if it's not available since the Nvidia operator comes packaged as a Helm chart.
if ! command -v helm &> /dev/null
then
  echo "Helm not found, installing Helm..."
  curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi

K="k3s kubectl"
SCRIPT_DIR=$(dirname "$0")

check_nvidia_drivers_and_container_runtime

# Install k3s using our standard script
$SCRIPT_DIR/install-k3s.sh

# Add the NVIDIA GPU Operator Helm repository
helm repo add nvidia https://nvidia.github.io/gpu-operator
helm repo update

# Get the latest version of the GPU Operator (the second field on the second line of the search result)
LATEST_VERSION=$(helm search repo nvidia/gpu-operator --devel --versions | awk 'NR == 2 {print $2}')

# Install the GPU Operator using Helm
echo "Installing NVIDIA GPU Operator version $LATEST_VERSION..."
helm install \
    --wait \
    --generate-name \
    -n gpu-operator \
    --create-namespace \
    --version "$LATEST_VERSION" \
    nvidia/gpu-operator

echo "NVIDIA GPU Operator installation completed."

# Verify that we actually added GPU capacity to the node
capacity=$($K get $($K get nodes -o name) -o=jsonpath='{.status.capacity.nvidia\.com/gpu}')
if [ "$capacity" = "1" ]; then
  echo "GPU capacity successfully added"
else
  echo "WARNING: No GPU capacity on node after install!!"
fi

# In addition, you can also check that the nvidia-device-plugin-ds pod
# is running in the `kube-system` namespace.
# kubectl get pods -n kube-system -l name=nvidia-device-plugin-ds
