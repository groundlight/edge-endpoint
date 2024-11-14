#!/bin/sh

set -eux

# Kill any existing k3s server processes
# WARNING: This will delete all cluster data!
pkill -f k3s || true
rm -rf /var/lib/rancher/k3s/*
sleep 2

# https://docs.k3s.io/cli/server
# https://docs.k3s.io/datastore/ha-embedded
# https://github.com/balena-io-experimental/balena-k3s/blob/main/server/server.sh

mount --make-rshared /

# Restart containerd, since `nvidia-ctk runtime configure --runtime=containerd` will have modified the containerd config
# systemctl restart containerd

# Copy our manifests to the K3s manifests directory. Any manifests in this directory will be automatically applied
# to the cluster by K3s. This is how we deploy the NVIDIA GPU operator, among other things.
# https://docs.k3s.io/installation/packaged-components#auto-deploying-manifests-addons
mkdir -p /var/lib/rancher/k3s/server/manifests/
cp /opt/k3s/manifests/* /var/lib/rancher/k3s/server/manifests/

# NOTE: this script is only intended to support a single-node "cluster". Multi-node
# clusters require using ectd as a datastore, instead of the default mysql. Etcd
# doesnt work well when the underlying storage is an sd card, like on raspberry pi.
# If we ever do want multi-node we'd have to pass `--server` or `--cluster-init` args to k3s
exec /usr/local/bin/k3s server ${EXTRA_K3S_SERVER_ARGS:-}