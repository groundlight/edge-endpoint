#!/bin/bash

# If the IP is changed, we'll need to restart some parts of the Kubernetes stuff
# Basically the K8s "node" object has the IP address in it and that doesn't change
# when the IP address changes. So we delete the node and restart the k3s service which
# will create a new node with the right address.

# Right now, this is pretty simple and basically recreates the whole edge endpoint.
# I think that we could get a little more fine-grained with this and figure out how
# to just recreate the persistent volumes cleanly, but this is good enough for now.

set -e # exit on error

host_address=$(ip route get 1.1.1.1 | awk '{print $7}')
node_address=$(kubectl get nodes  -o custom-columns='INTERNAL-IP:.status.addresses[?(@.type=="InternalIP")].address' --no-headers)

if [ "${host_address}" = "${node_address}" ]; then
    echo "Host address and node address are the same. No need to restart."
    exit 0
fi

# Find all the namespaces that are running edge-endpoint so that we can remove the deployments
# and disconnect the persistent volume
mapfile -t namespaces < <(kubectl get deployments -A | awk '$2=="edge-endpoint" {print $1}')

for ns in "${namespaces[@]}"; do
    kubectl delete deployment -n ${ns} edge-endpoint
    for d in $(kubectl get -n $ns deployment --ignore-not-found | awk '$1 ~ /^inferencemodel-/ {print $1}'); do
        kubectl delete deployment -n ${ns} $d
    done
    kubectl delete pvc -n ${ns} --ignore-not-found edge-endpoint-pvc
done

# Deleting the PVs doesn't really delete the data since they are all mapped to 
# the underlying host directory and will be recreated when we set back up
for pv in $(kubectl get pv | awk '$1 ~ /^edge-endpoint-pv/ {print $1}'); do
    kubectl delete pv ${pv}
done

old_node=$(kubectl get node --no-headers | awk '{print $1}')

kubectl delete node ${old_node}

# Now restart the k3s service to get the reconfigured node up
sudo systemctl restart k3s.service

sleep 5 # let the basic service start

# Now wait for coredns to be ready, once that's up, we should be good to go
kubectl rollout status deployment coredns -n kube-system --timeout=10m # This should really only take a few seconds

echo "Kubernetes node is updated. Recreating edge endpoint resources in all namespaces"

for ns in "${namespaces[@]}"; do
    echo "Creating resources in ${ns}"
    DEPLOYMENT_NAMESPACE="${ns}" "$(dirname "$0")"/setup-ee.sh
done
