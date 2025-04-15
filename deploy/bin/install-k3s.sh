#!/bin/bash
cd "$(dirname "$0")"

set -e

K="k3s kubectl"

#!/bin/bash

# Validate number of arguments
if [ "$#" -ne 1 ]; then
    echo "❌ Error: Exactly one argument is required: 'gpu' or 'cpu'." >&2
    exit 1
fi

# Convert to lowercase
FLAVOR=$(echo "$1" | tr '[:upper:]' '[:lower:]')

# Validate value
if [ "$FLAVOR" != "gpu" ] && [ "$FLAVOR" != "cpu" ]; then
    echo "❌ Error: Argument must be either 'gpu' or 'cpu'." >&2
    exit 1
fi

# Confirm success
echo "Flavor set to: $FLAVOR"

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
        
        # Check if memory controller is available and enabled in cgroup v2
        if [ -f "/sys/fs/cgroup/cgroup.controllers" ] && 
           grep -q "memory" "/sys/fs/cgroup/cgroup.controllers" ] && 
           [ -f "/sys/fs/cgroup/cgroup.subtree_control" ] && 
           grep -q "memory" "/sys/fs/cgroup/cgroup.subtree_control"; then
            echo "Memory controller is properly enabled in cgroup v2."
            return 0
        else
            echo "Cgroup v2 is mounted but memory controller is not properly enabled."
            return 1
        fi
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
Cgroup memory controller is not properly enabled. K3s requires this to function.

There are two possible fixes depending on your system:

1. For most modern Linux distributions (Ubuntu 22.04+, Debian 11+, newer Raspberry Pi OS):
   Add to kernel command line:
      cgroup_memory=1 cgroup_enable=memory systemd.unified_cgroup_hierarchy=1
   
   This enables memory cgroups and specifically configures systemd to use the unified 
   cgroup v2 hierarchy, which is the modern approach.

2. For older systems or if option 1 doesn't work:
   Add to kernel command line:
      cgroup_memory=1 cgroup_enable=memory
   
   This enables basic memory cgroup support which works with cgroup v1 systems.

For Raspberry Pi: Edit /boot/cmdline.txt or /boot/firmware/cmdline.txt
For most other systems: Edit GRUB configuration via /etc/default/grub

After modifying the kernel command line, a reboot is required.

Note: Some systems running older kernels (pre-5.2) or using alternative init systems 
may need to research specific cgroup configuration for their environment.
EOF
    exit 1
fi

# Install and configure GPU support, if requested
# Tested on an AWS EC2 G4 instance using the following AMI:
# Deep Learning OSS Nvidia Driver AMI GPU PyTorch 2.3.0 (Ubuntu 20.04) 20240825

# This guide was more helpful than others fwiw:
# https://support.tools/post/nvidia-gpus-on-k3s/


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

if [ "$FLAVOR" == "gpu" ]; then
    echo
    echo '##################################################################################'
    echo '# Installing driver support for NVIDIA GPUs'
    echo '##################################################################################'
    check_nvidia_drivers_and_container_runtime
    echo "NVIDIA GPU support installed."
fi

echo
echo '##################################################################################'
echo '# Installing k3s'
echo '##################################################################################'

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

# If k3s is already installed, we can skip the installation, but we need to do
# a couple of checks to make sure it's running and configured correctly.

if command -v k3s &> /dev/null; then
    echo "k3s is already installed. Checking status..."
    if ! k3s kubectl get nodes &> /dev/null; then
        echo "k3s is not running. Restart it or uninstall it and run this script again."
        exit 1
    else
        echo "k3s is running."
    fi
else
    echo "k3s is not installed. Installing..."
    curl -sfL https://get.k3s.io |  K3S_KUBECONFIG_MODE="644" sh -s - --disable=traefik

    if check_k3s_is_running; then
        echo "k3s has installed and initialized successfully."
    else
        echo "There was an issue with the K3s installation. Please check the system logs."
        exit 0
    fi
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

install_nvidia_operator() {
    helm repo add nvidia https://nvidia.github.io/gpu-operator
    helm repo update

    helm upgrade -i nvidia-gpu-operator nvidia/gpu-operator \
        --namespace gpu-operator \
        --create-namespace \
        --set driver.enabled=false \
        --set toolkit.enabled=false
}

wait_for_gpu() {
    # Verify that we actually added GPU capacity to the node
    local capacity=0
    local elapsed=0
    # Even 5 minutes isn't enough sometimes.
    local timeout_min=10

    echo
    echo "Waiting up to $timeout_min minutes for the GPU capacity to come online:"

    timeout_sec=$((timeout_min * 60))
    while [ "$elapsed" -lt "$timeout_sec" ]; do
        node_name=$($K get nodes -o name | head -n1)
        # First make sure the node has registered
        if [ -z "$node_name" ]; then
            echo -n "Waiting for node to register..."
            sleep 1
            ((elapsed++)) || true
            continue
        fi

        # Now check the GPU capacity for the node
        capacity=$($K get "$node_name" -o=jsonpath='{.status.capacity.nvidia\.com/gpu}')

        # Check if GPU capacity is non-zero
        if [ -n "$capacity" ] && [ "$capacity" -ne 0 ]; then
            break
        fi

        echo -n "."

        # Wait for 1 second
        sleep 1
        ((elapsed++)) || true
    done

    echo
    capacity=${capacity:-0}
    if [ $capacity -gt 0 ]; then
        echo "GPU capacity successfully added"
    else
        echo "WARNING: k3s sees no GPU capacity on node after install!!"
        if ! nvidia-smi &> /dev/null; then
            echo "Running nvidia-smi failed, so NVIDIA drivers are probably not working."
            echo "Rebooting might help."
        fi
        exit 1
    fi
}

if [ "$FLAVOR" == "gpu" ]; then
    echo
    echo '##################################################################################'
    echo '# Installing NVidia Kubernetes Operator'
    echo '##################################################################################'

    install_nvidia_operator
    echo "NVIDIA GPU Operator installation completed."
    
    echo
    echo '##################################################################################'
    echo '# Waiting for GPU capacity to come online'
    echo '##################################################################################'

    wait_for_gpu
fi

# In addition, you can also check that the nvidia-device-plugin-ds pod
# is running in the `kube-system` namespace.
# kubectl get pods -n kube-system -l name=nvidia-device-plugin-ds


echo
echo '##################################################################################'
echo '# Installation successful'
echo '##################################################################################'


