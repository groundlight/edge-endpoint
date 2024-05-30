#!/bin/sh

set -eu

# https://docs.k3s.io/cli/server
# https://docs.k3s.io/datastore/ha-embedded
# https://github.com/balena-io-experimental/balena-k3s/blob/main/server/server.sh


# NOTE: this script is only intended to support a single-node "cluster". Multi-node
# clusters require using ectd as a datastore, instead of the default mysql. Etcd
# doesnt work well when the underlying storage is an sd card, like on raspberry pi.
exec /bin/k3s server ${EXTRA_K3S_SERVER_ARGS:-}
