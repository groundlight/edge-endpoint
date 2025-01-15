#! /bin/bash
# This script is intended to run on a new ubuntu instance to set it up 
# Sets up an edge-endpoint environment.

# As a user-data script, on ubuntu,
# - this file will show up in /var/lib/cloud/instance/user-data.txt
# - it will log to /var/log/cloud-init-output.log

echo "First-run script starting at $(date)!"

sudo apt update
sudo apt install -y \
    git \
    vim \
    tmux \
    htop \
    curl \
    wget \
    tree \
    ffmpeg

TARGET_USER="ubuntu"

# Clone edge-endpoint code into target user's home directory
# (Note we can't just `su ubuntu` here.)
mkdir -p /home/${TARGET_USER}/ptdev/
cd /home/${TARGET_USER}/ptdev/
git clone https://github.com/groundlight/edge-endpoint
chown -R ${TARGET_USER}:${TARGET_USER} /home/${TARGET_USER}/ptdev/
cd edge-endpoint/

# Set up k3s with GPU support
./deploy/bin/install-k3s-nvidia.sh

# Prepare kubernetes
kubectl create namespace gl-edge
kubectl config set-context edge --namespace=gl-edge --cluster=default --user=default
kubectl config use-context edge
echo "alias k='kubectl'" >> /home/${TARGET_USER}/.bashrc
echo "set -o vi" >> /home/${TARGET_USER}/.bashrc

# Configure the edge-endpoint with environment variables
export DEPLOYMENT_NAMESPACE="gl-edge"
export INFERENCE_FLAVOR="GPU"
export GROUNDLIGHT_API_TOKEN="api_placeholder"

# Install the edge-endpoint
./deploy/bin/setup-ee.sh

echo "First-run script complete at $(date)"