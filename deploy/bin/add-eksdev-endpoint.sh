#!/bin/bash

# Update the k3s CoreDNS ConfigMap to add a new DNS entry for the dev API endpoint
# so we can test against our eksdev environment (api.dev.groundlight.ai).

# Check if the correct number of arguments was provided
if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <ip-address>"
    exit 1
fi

HOSTNAME=api.dev.groundlight.ai
IP_ADDRESS=$1

K=${KUBECTL_CMD:-kubectl}

# Before starting, confirm that we're in the k3s cluster. It would be bad to accidentally
# update the CoreDNS ConfigMap in a shared cluster.

$K get nodes | grep -q "+k3s1" || {
    echo "This script should only be run in a k3s cluster."
    exit 1
}

# Define a function to update the CoreDNS ConfigMap
update_coredns_configmap() {
    # Fetch the current CoreDNS ConfigMap
    $K get configmap coredns -n kube-system -o yaml > /tmp/coredns_cm.yaml
    
    # Check if the host entry already exists to prevent duplicates
    if grep -q "^ *$IP_ADDRESS $HOSTNAME" /tmp/coredns_cm.yaml; then
        echo "Entry for $HOSTNAME ($IP_ADDRESS) already exists in CoreDNS. No changes made."
        exit 0
    fi

    # If it exists with a different name, delete it
    if grep -q "^ *[.0-9][.0-9]* *$HOSTNAME" /tmp/coredns_cm.yaml; then
        echo "Entry for $HOSTNAME with a different IP address exists in CoreDNS. Deleting it."
        sed -i "/^ *[.0-9][.0-9]* *$HOSTNAME/d" /tmp/coredns_cm.yaml
    fi

    # Append the new entry inside the existing "hosts" block if it exists
    if grep -q "^ *hosts /etc/coredns/NodeHosts {" /tmp/coredns_cm.yaml; then
        sed -i "/^ *hosts \/etc\/coredns\/NodeHosts {/a \          $IP_ADDRESS $HOSTNAME" /tmp/coredns_cm.yaml
    else
        # If no "hosts" block exists, insert a new one before "forward"
        sed -i "/^    forward . \/etc\/resolv.conf/i \
\        hosts {\n          $IP_ADDRESS $HOSTNAME\n          fallthrough\n        }" /tmp/coredns_cm.yaml
    fi

    # Apply the modified ConfigMap
    $K apply -f /tmp/coredns_cm.yaml
}

# Update CoreDNS ConfigMap
update_coredns_configmap

# Cleanup temporary file
rm /tmp/coredns_cm.yaml

# Restart CoreDNS to apply changes
$K -n kube-system rollout restart deployment coredns

echo "DNS entry for $HOSTNAME with IP $IP_ADDRESS added and CoreDNS restarted."
