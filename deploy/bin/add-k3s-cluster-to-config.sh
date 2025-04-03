#!/bin/bash

# Copy the cluster information defined in the k3s config file to the user's kubeconfig file
# If the user already has a kubeconfig file, add the cluster information to the existing file
# otherwise create a new kubeconfig file

set -e

# Don't use `k3s kubectl` here because it always uses the default kubeconfig file in /etc/rancher/k3s/k3s.yaml
K=${KUBECTL_CMD:-kubectl}

k3scfg="/etc/rancher/k3s/k3s.yaml"

kubectl_is_k3s=$($K version --client | egrep "^Client Version.*+k3s" || true)

if [ -n "$kubectl_is_k3s" ]; then
    echo "Using the kubectl supplied by k3s. Shared kubeconfig file is at ${k3scfg}"
    echo "If you want to use a different kubeconfig, set the KUBECONFIG environment variable"
    exit 0
fi

if [ -f $k3scfg ]; then
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
else
    echo "ERROR: k3s config file ('${k3scfg}') not found"
    exit 1
fi