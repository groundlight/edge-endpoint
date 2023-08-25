#!/bin/bash 

# Check if k3s is installed 
if command -v k3s &> /dev/null; then
    echo "k3s is already installed."
    exit 0
fi 


echo "Installing k3s..."

# Update system 
sudo apt update && sudo apt upgrade -y 

# Install k3s
curl -sfL https://get.k3s.io | sh -


check_k3s_is_running() {
    local TIMEOUT=20 # Maximum wait time of 30 seconds
    local COUNT=0

    while [ $COUNT -lt $TIMEOUT ]; do
        if kubectl get ns >/dev/null 2>&1; then
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
   sudo chmod 666 /etc/rancher/k3s/k3s.yaml
   echo "kubectl has been configured for the current user."
else
    echo "There was an issue with the K3s installation. Please check the system logs."
fi
