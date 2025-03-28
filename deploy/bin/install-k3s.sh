#!/bin/bash
cd "$(dirname "$0")"

set -e

K="k3s kubectl"

echo '##################################################################################'
echo '# Starting installation: updating system and installing dependencies'
echo '##################################################################################'
# Update system
sudo apt update && sudo apt upgrade -y && sudo apt install -y jq curl

echo
echo '##################################################################################'
echo '# Check that cgroups are set up in the OS in a way that supports k3s'
echo '##################################################################################'

# Function to check if memory cgroups are actually working
check_cgroup() {
    if mount | grep -q "cgroup2"; then
        echo "Cgroup v2 is enabled."
        return 0
    elif mount | grep -q "cgroup/memory"; then
        # For cgroup v1, verify memory controller is actually functional
        if [ -f "/sys/fs/cgroup/memory/memory.limit_in_bytes" ]; then
            echo "Cgroup v1 (memory) is enabled and functional."
            return 0
        else
            echo "Cgroup v1 memory controller found but may not be functional."
            echo "You may need to add 'cgroup_memory=1 cgroup_enable=memory' to kernel command line."
            return 1
        fi
    else
        echo "No memory cgroup found."
        echo "You may need to add 'cgroup_memory=1 cgroup_enable=memory' to kernel command line."
        return 1
    fi
}

check_cgroup
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

echo
echo '##################################################################################'
echo '# Installing k3s'
echo '##################################################################################'

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

echo
echo '##################################################################################'
echo '# Setting up kubeconfig for the current user'
echo '##################################################################################'

# Copy the cluster information defined in the k3s config file to the user's kubeconfig file
# If the user already has a kubeconfig file, add the cluster information to the existing file
# otherwise create a new kubeconfig file

add_kubectl_config() {
    # Don't use `k3s kubectl` here because it always uses the default kubeconfig file in /etc/rancher/k3s/k3s.yaml
    local K=${KUBECTL_CMD:-kubectl}


    local k3scfg="/etc/rancher/k3s/k3s.yaml"

    local kubectl_is_k3s=$($K version --client | egrep "^Client Version.*+k3s" || true)

    if [ ! -f $k3scfg ]; then
        echo "ERROR: k3s config file ('${k3scfg}') not found"
        exit 1
    fi

    export KUBECONFIG=$HOME/.kube/config

    if [ -n "$kubectl_is_k3s" ]; then
        echo "Using the kubectl supplied by k3s. Shared kubeconfig file is at ${k3scfg}"
        echo "We'll copy that info to the user's kubeconfig file so that Helm can find it."
        
        if [ -f $HOME/.kube/config ]; then
            echo "User's kubeconfig file already exists. Adding cluster information to the existing file."
        else
            echo "User's kubeconfig file does not exist. Creating a new kubeconfig file."
            mkdir -p $HOME/.kube
            $K config view --kubeconfig=${k3scfg} --minify --flatten --output 'jsonpath={.clusters[?(@.name=="default")].cluster}' > $HOME/.kube/config
        fi
    fi

    # Get the cluster and user information from the k3s config file
    server=$($K config view --kubeconfig="${k3scfg}" --minify --flatten --output 'jsonpath={.clusters[?(@.name=="default")].cluster.server}')
    cert=$($K config view --kubeconfig="${k3scfg}" --minify --flatten --output 'jsonpath={.clusters[?(@.name=="default")].cluster.certificate-authority-data}')

    user_client_certificate=$(kubectl config view --kubeconfig=${k3scfg} --minify --flatten --output 'jsonpath={.users[?(@.name=="default")].user.client-certificate-data}')
    user_client_key=$(kubectl config view --kubeconfig=${k3scfg} --minify --flatten --output 'jsonpath={.users[?(@.name=="default")].user.client-key-data}')

    # Add the cluster information to the user's kubeconfig file
    $K config set-cluster k3s --server=$server --certificate-authority=<(echo "${cert}" | base64 -d) --embed-certs=true
    $K config set-credentials k3s \
    --embed-certs=true \
    --client-certificate=<(echo "${user_client_certificate}" | base64 -d) \
    --client-key=<(echo "${user_client_key}" | base64 -d)

    # create a context that points to the default namespace in the new cluster
    $K config set-context k3s --cluster=k3s --user=k3s
    $K config use-context k3s
}

add_kubectl_config
echo "kubectl has been configured for the current user."

echo
echo '##################################################################################'
echo '# Installing helm and connecting to our helm repo'
echo '##################################################################################'

curl -fsSL -o /tmp/get_helm.sh https://raw.githubusercontent.com/helm/helm/master/scripts/get-helm-3
chmod 700 /tmp/get_helm.sh
/tmp/get_helm.sh

# Add the edge-endpoint helm repo
helm repo add edge-endpoint https://code.groundlight.ai/edge-endpoint/
helm repo update

echo
echo '##################################################################################'
echo '# Installation successful'
echo '##################################################################################'


