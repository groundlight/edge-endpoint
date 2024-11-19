#!/bin/sh

# Start the k3s server. This script is intended to be run in the balena-k3s server container.
# This script loosely based on https://github.com/balena-io-experimental/balena-k3s/blob/main/server/server.sh

set -eux

# Kill any existing k3s server processes and reset them -
# WARNING: this will remove all cluster data such as running pods, services, etc.
pkill -f k3s || true
rm -rf /var/lib/rancher/k3s/*
sleep 2

# Inference flavor can be either "CPU" or "GPU". If not set, default to "GPU".
INFERENCE_FLAVOR="${INFERENCE_FLAVOR:-GPU}"

if [ "${INFERENCE_FLAVOR}" = "GPU" ]; then
    # Make the root filesystem shared to allow NVIDIA driver modules to be loaded properly
    mount --make-rshared /

    # Copy our manifests to the K3s manifests directory. Any manifests in this directory will be
    # automatically applied to the cluster by K3s. This is how we deploy the NVIDIA GPU operator,
    # so we only do this if we're using GPU inference.
    # https://docs.k3s.io/installation/packaged-components#auto-deploying-manifests-addons
    mkdir -p /var/lib/rancher/k3s/server/manifests/
    cp /opt/k3s/manifests/* /var/lib/rancher/k3s/server/manifests/
fi

# NOTE: this script is only intended to support a single-node "cluster".
# Multi-node clusters require using ectd as a datastore, instead of the k8s default mysql.
# Etcd doesnt work well when the underlying storage is an sd card, like on raspberry pi.
# If we ever do want multi-node we'd have to pass `--server` or `--cluster-init` args to k3s.
# https://docs.k3s.io/cli/server
# https://docs.k3s.io/datastore/ha-embedded
exec /usr/local/bin/k3s server ${EXTRA_K3S_SERVER_ARGS:-}