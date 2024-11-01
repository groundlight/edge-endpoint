#!/bin/sh

set -eux

# https://docs.k3s.io/cli/server
# https://docs.k3s.io/datastore/ha-embedded
# https://github.com/balena-io-experimental/balena-k3s/blob/main/server/server.sh

# Copy our manifests to the K3s manifests directory
mkdir -p /var/lib/rancher/k3s/server/manifests/
cp /opt/k3s/manifests/* /var/lib/rancher/k3s/server/manifests/

# NOTE: this script is only intended to support a single-node "cluster". Multi-node
# clusters require using ectd as a datastore, instead of the default mysql. Etcd
# doesnt work well when the underlying storage is an sd card, like on raspberry pi.
# If we ever do want multi-node we'd have to pass `--server` or `--cluster-init` args to k3s
exec /usr/local/bin/k3s server ${EXTRA_K3S_SERVER_ARGS:-}