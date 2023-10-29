#!/bin/bash

# Install k3s and configures GPU support
# Designed for Intel servers with NVIDIA GPUs.
# Tested on an AWS EC2 G4 instance using the following AMI:
# Deep Learning AMI GPU PyTorch 2.0.1 (Ubuntu 20.04) 20230827

# This guide was more helpful than others fwiw:
# https://support.tools/post/nvidia-gpus-on-k3s/

set -ex

check_nvidia_drivers_and_container_runtime() {
  # Figure out what version of nvidia drivers to use.
  # first check if something is already installed
  NVIDIA_VERSION=$(modinfo nvidia 2>/dev/null | awk '/^version:/ {split($2, a, "."); print a[1]}')
  if [ -z "$NVIDIA_VERSION" ]; then
    echo "Did not find nvidia drivers installed.  Defaultint to 525"
    NVIDIA_VERSION=525
  fi

  if ! dpkg -l | grep -q "nvidia.*-$NVIDIA_VERSION"; then
    echo " Can't find NVIDIA drivers installed. Installing nvidia-headless-$NVIDIA_VERSION-server..."
    sudo apt install -y nvidia-headless-$NVIDIA_VERSION-server
  else
    echo " NVIDIA drivers for version $NVIDIA_VERSION appear to likely be installed."
  fi

  # Check if nvidia container runtime is already installed. 
  if ! command -v nvidia-container-runtime &> /dev/null; then 
    echo " NVIDIA container runtime is not installed. Installing..."
    # Get distribution information 
    distribution=$(. /etc/os-release; echo $ID$VERSION_ID)

    # Define the NVIDIA GPG key URL
    NVIDIA_GPG_URL="https://nvidia.github.io/nvidia-docker/gpgkey"

    # Define the NVIDIA Docker repository list URL
    NVIDIA_REPO_LIST_URL="https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list"

    # Define the keyring file path
    KEYRING="/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg"

    # Define the repository list file path
    REPO_LIST_FILE="/etc/apt/sources.list.d/nvidia-docker.list"

    echo "Adding NVIDIA Docker repository..."

    # Download and save the GPG key to the keyring file
    curl -s -L $NVIDIA_GPG_URL | gpg --dearmor | sudo tee $KEYRING > /dev/null

    # Download the repository source list and add it to APT sources with the signed-by option
    curl -s -L $NVIDIA_REPO_LIST_URL | \
    sed "s/deb /deb [signed-by=$KEYRING] /" | \
    sudo tee $REPO_LIST_FILE > /dev/null

    # Update package lists and install
    sudo apt update -y && sudo apt install -y nvidia-container-runtime
  else
    echo " NVIDIA container runtime is installed."
  fi
}


K="k3s kubectl"
SCRIPT_DIR=$(dirname "$0")

# Install k3s using our standard script
$SCRIPT_DIR/install-k3s.sh

check_nvidia_drivers_and_container_runtime

# Configure k3s to use nvidia-container-runtime
# See guide here: https://k3d.io/v5.3.0/usage/advanced/cuda/#configure-containerd 
echo "Configuring k3s to use nvidia-container-runtime..."
for i in {1..10}; do
  if [[ -f "/var/lib/rancher/k3s/agent/etc/containerd/config.toml.tmpl" ]]; then
    break
  fi
  # Sometimes the following wget fails initially but works after a few seconds
  sleep 2
  sudo wget https://k3d.io/v5.3.0/usage/advanced/cuda/config.toml.tmpl -O /var/lib/rancher/k3s/agent/etc/containerd/config.toml.tmpl && break
done

# Enable nvidia-device-plugin via a DaemonSet and add a RuntimeClass definition for it
# https://github.com/NVIDIA/k8s-device-plugin/?tab=readme-ov-file#enabling-gpu-support-in-kubernetes
echo "Creating nvidia RuntimeClass and nvidia-device-plugin DaemonSet..."
$K apply -f - <<EOF
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: nvidia
handler: nvidia
---
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: nvidia-device-plugin-daemonset
  namespace: kube-system
spec:
  selector:
    matchLabels:
      name: nvidia-device-plugin-ds
  updateStrategy:
    type: RollingUpdate
  template:
    metadata:
      labels:
        name: nvidia-device-plugin-ds
    spec:
      tolerations:
      - key: nvidia.com/gpu
        operator: Exists
        effect: NoSchedule
      # Mark this pod as a critical add-on; when enabled, the critical add-on
      # scheduler reserves resources for critical add-on pods so that they can
      # be rescheduled after a failure.
      # See https://kubernetes.io/docs/tasks/administer-cluster/guaranteed-scheduling-critical-addon-pods/
      priorityClassName: "system-node-critical"
      # (GROUNDLIGHT) REQUIRED MODIFICATION FOR K3S:
      runtimeClassName: nvidia
      containers:
      - image: nvcr.io/nvidia/k8s-device-plugin:v0.14.1
        name: nvidia-device-plugin-ctr
        env:
          - name: FAIL_ON_INIT_ERROR
            value: "false"
        securityContext:
          allowPrivilegeEscalation: false
          capabilities:
            drop: ["ALL"]
        volumeMounts:
        - name: device-plugin
          mountPath: /var/lib/kubelet/device-plugins
      volumes:
      - name: device-plugin
        hostPath:
          path: /var/lib/kubelet/device-plugins
EOF

# You can verify correctness by running `kubectl get node`
# and inspecting "Capacity" section for "nvidia.com/gpu".

# In addition, you can also check that the nvidia-device-plugin-ds pod 
# is running in the `kube-system` namespace. 
# kubectl get pods -n kube-system -l name=nvidia-device-plugin-ds
