#!/bin/bash

# Install k3s and configure GPU support
# Tested on an AWS EC2 G4 instance using the following AMI:
# Deep Learning AMI GPU PyTorch 2.0.1 (Ubuntu 20.04) 20230827

set -e

# Check if k3s is installed
if command -v k3s &> /dev/null; then
    echo "k3s is already installed."
    exit 0
fi

K="k3s kubectl"

# Update system
sudo apt update && sudo apt upgrade -y

# Install k3s
echo "Installing k3s..."
curl -sfL https://get.k3s.io | K3S_KUBECONFIG_MODE="644" sh -

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
    # Configure kubectl for the current user
    echo "kubectl has been configured for the current user."
else
    echo "There was an issue with the K3s installation. Please check the system logs."
    exit 0
fi

sleep 5  # Sometimes the following wget fails initially, but after waiting a few seconds it works

# Configure k3s to use nvidia-container-runtime
# See guide here: https://k3d.io/v5.3.0/usage/advanced/cuda/#configure-containerd
echo "Configuring k3s to use nvidia-container-runtime..."
sudo wget https://k3d.io/v5.3.0/usage/advanced/cuda/config.toml.tmpl -O /var/lib/rancher/k3s/agent/etc/containerd/config.toml.tmpl

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