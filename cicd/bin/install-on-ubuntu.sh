#! /bin/bash
# This script is intended to run on a new ubuntu instance to set it up 
# Sets up an edge-endpoint environment.
# It is tested in the CICD pipeline to install the edge-endpoint on a new 
# g4dn.xlarge EC2 instance with Ubuntu 22.04LTS.

# As a user-data script on ubuntu, this file probably lands at
# /var/lib/cloud/instance/user-data.txt
echo "Setting up Groundlight Edge Endpoint.  Follow along at /var/log/cloud-init-output.log" > /etc/motd

echo "Starting cloud init.  Uptime: $(uptime)"

# Set up signals about the status of the installation
mkdir -p /opt/groundlight/ee-install-status
touch /opt/groundlight/ee-install-status/installing
SETUP_COMPLETE=0
record_result() {
    if [ "$SETUP_COMPLETE" -eq 0 ]; then
        echo "Setup failed at $(date)"
        touch /opt/groundlight/ee-install-status/failed
        echo "Groundlight Edge Endpoint setup FAILED.  See /var/log/cloud-init-output.log for details." > /etc/motd
    else
        echo "Setup complete at $(date)"
        echo "Groundlight Edge Endpoint setup complete.  See /var/log/cloud-init-output.log for details." > /etc/motd
        touch /opt/groundlight/ee-install-status/success
    fi
    # Remove "installing" at the end to avoid a race where there is no status
    rm -f /opt/groundlight/ee-install-status/installing
}
trap record_result EXIT

set -e  # Exit on error of any command.

# Install the basic tools
sudo apt update
sudo apt install -y \
    git \
    vim \
    tmux \
    htop \
    curl \
    wget \
    tree \
    bash-completion \
    ffmpeg

TARGET_USER="ubuntu"
# cloud-init script runs as root, but we will mostly install things in ubuntu

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
echo "source <(kubectl completion bash)" >> /home/${TARGET_USER}/.bashrc
echo "complete -F __start_kubectl k" >> /home/${TARGET_USER}/.bashrc
echo "set -o vi" >> /home/${TARGET_USER}/.bashrc

# Configure the edge-endpoint with environment variables
export DEPLOYMENT_NAMESPACE="gl-edge"
export INFERENCE_FLAVOR="GPU"
export GROUNDLIGHT_API_TOKEN="api_placeholder"

# Install the edge-endpoint
./deploy/bin/setup-ee.sh

# Indicate that setup is complete
SETUP_COMPLETE=1
echo "EE is installed into kubernetes, which will attempt to finish the setup."