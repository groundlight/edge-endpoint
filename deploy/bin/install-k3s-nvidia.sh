#!/bin/bash

# Install k3s and configure GPU support
# This does the GPU stuff, but calls the other install-k3s.sh script to do the rest.
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
    sudo apt update && sudo apt install -y "nvidia-headless-$NVIDIA_VERSION-server" "nvidia-utils-$NVIDIA_VERSION-server"
  else
    echo "NVIDIA drivers for version $NVIDIA_VERSION are installed."
  fi

  # Check if nvidia container runtime is already installed.
  if ! command -v nvidia-container-runtime &> /dev/null; then
    echo " NVIDIA container runtime is not installed. Installing..."
    # Get distribution information
    DISTRIBUTION=$(. /etc/os-release; echo "$ID$VERSION_ID")

    if ! command -v curl &> /dev/null; then
      echo "Installing curl to retrieve NVIDIA repository info"
      sudo apt update -y && sudo apt install -y curl
    fi
  
    # Add NVIDIA Docker repository
    echo "Adding NVIDIA Docker repository..."
    curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
    curl -s -L "https://nvidia.github.io/nvidia-docker/$DISTRIBUTION/nvidia-docker.list" | sudo tee /etc/apt/sources.list.d/nvidia-docker.list

    sudo apt update -y && sudo apt install -y nvidia-container-runtime
  else
    echo " NVIDIA container runtime is installed."
  fi
}

K="k3s kubectl"
SCRIPT_DIR=$(dirname "$0")

check_nvidia_drivers_and_container_runtime

# Install k3s using our standard script
$SCRIPT_DIR/install-k3s.sh

$K apply -f ${SCRIPT_DIR}/helm-nvidia-operator.yaml


echo "NVIDIA GPU Operator installation completed."

# Verify that we actually added GPU capacity to the node
capacity=0
elapsed=0
timeout=60

while [ "$elapsed" -lt "$timeout" ]; do
    # Run the command and capture its output
    capacity=$($K get $($K get nodes -o name) -o=jsonpath='{.status.capacity.nvidia\.com/gpu}')

    # Check if the command output is non-zero
    if [ -n "$capacity" ] && [ "$capacity" -ne 0 ]; then
        break
    fi

    # Wait for 1 second
    sleep 1
    ((elapsed++)) || true  # Increment elapsed time (returns a non-zero code??)
done


if [ "$capacity" = "1" ]; then
  echo "GPU capacity successfully added"
else
  echo "WARNING: No GPU capacity on node after install!!"
fi

# In addition, you can also check that the nvidia-device-plugin-ds pod
# is running in the `kube-system` namespace.
# kubectl get pods -n kube-system -l name=nvidia-device-plugin-ds
