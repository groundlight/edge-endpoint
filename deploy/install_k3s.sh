#!/bin/bash 

# Check if k3s is installed 
if command -v k3s &> /dev/null; then
    echo "K3s is already instaled."
else
    echo "Installing K3s..."

    # Update system 
    sudo apt update && sudo apt upgrade -y 

    # Install k3s
    curl -sfL https://get.k3s.io | sh -

    # Wait for k3s to start 
    sleep 10

    # Check k3s status 
    if sudo systemctl is-active --quiet k3s; then
        echo "K3s installed successfully."

        # Configure kubectl for the current user
        mkdir -p ~/.kube 
        sudo chown $USER:$USER /etc/rancher/k3s/k3s.yaml 

        echo "kubectl has been configured for the current user."
    else
        echo "There was an issue with the K3s installation. Please check the system logs."
    fi
fi
    