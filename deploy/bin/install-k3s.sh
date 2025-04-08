#!/bin/bash
cd "$(dirname "$0")"

set -e

K="k3s kubectl"

# Update system
sudo apt update && sudo apt upgrade -y && sudo apt install -y jq curl

# Check cgroup setup
./check_cgroup.sh
CGROUP_STATUS=$?

if [ $CGROUP_STATUS -eq 1 ]; then
    cat << EOF
Cgroup setup is NOT correct.  k3s will probably not work on this system.
To fix, add the following to the kernel command line in your bootloader configuration:
    cgroup_memory=1 cgroup_enable=memory
You can do this with grub on most systems,
or on Raspberry Pi by editing /boot/cmdline.txt or /boot/firmware/cmdline.txt.
EOF
    exit 1
fi

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
./add-k3s-cluster-to-config.sh

echo "You might want to set KUBECONFIG as follows:"
echo "export KUBECONFIG=/etc/rancher/k3s/k3s.yaml"

# Install helm
echo "Installing helm..."
curl -fsSL -o /tmp/get_helm.sh https://raw.githubusercontent.com/helm/helm/master/scripts/get-helm-3
chmod 700 /tmp/get_helm.sh
/tmp/get_helm.sh

