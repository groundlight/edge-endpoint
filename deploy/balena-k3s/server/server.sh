#!/bin/sh

set -eux

# https://docs.k3s.io/cli/server
# https://docs.k3s.io/datastore/ha-embedded
# https://github.com/balena-io-experimental/balena-k3s/blob/main/server/server.sh


# NOTE: this script is only intended to support a single-node "cluster". Multi-node
# clusters require using ectd as a datastore, instead of the default mysql. Etcd
# doesnt work well when the underlying storage is an sd card, like on raspberry pi.
# If we ever do want multi-node we'd have to pass `--server` or `--cluster-init` args to k3s

# Flush stale CNI portmap iptables rules left over from a previous K3s instance.
# After a container restart (e.g. balena device purge), K3s starts fresh but old
# CNI DNAT rules persist in the host kernel.  If a new pod gets a different IP
# than the old one, the stale rule matches first and routes traffic to a dead IP,
# causing "no route to host" on hostPort-exposed services (notably port 80).
# Flushing here is safe because K3s has not started yet -- there are no live pods
# whose rules we could accidentally remove.  K3s + CNI will recreate the correct
# rules when pods are scheduled.
if iptables -t nat -L CNI-HOSTPORT-DNAT -n >/dev/null 2>&1; then
    echo "Cleaning up stale CNI portmap iptables rules..."
    iptables -t nat -F CNI-HOSTPORT-DNAT 2>/dev/null || true
    iptables-save -t nat 2>/dev/null \
        | grep '^:CNI-DN-' \
        | sed 's/^:\([^ ]*\).*/\1/' \
        | while read chain; do
            iptables -t nat -F "$chain" 2>/dev/null || true
            iptables -t nat -X "$chain" 2>/dev/null || true
        done
    echo "CNI portmap cleanup complete"
fi

# Detect inference flavor and write to /shared/INFERENCE_FLAVOR for bastion to read
mkdir -p /shared
FLAVOR_FILE="/shared/INFERENCE_FLAVOR"
rm -f "$FLAVOR_FILE"

# Allow override via environment variable INFERENCE_FLAVOR
if [ -n "${INFERENCE_FLAVOR:-}" ]; then
    flavor="$(echo "$INFERENCE_FLAVOR" | tr '[:upper:]' '[:lower:]')"
else
    # Detect Jetson devices first
    if [ -f /etc/nv_tegra_release ] || grep -qi 'nvidia jetson' /proc/device-tree/model 2>/dev/null; then
        flavor="jetson"
    # Then detect NVIDIA GPUs on x86 (presence of device nodes or nvidia-smi)
    elif [ -e /dev/nvidia0 ] || command -v nvidia-smi >/dev/null 2>&1; then
        flavor="gpu"
    else
        flavor="cpu"
    fi
fi
echo "$flavor" > "$FLAVOR_FILE"

# Copy GPU operator manifests to the K3s auto-deploy directory if they exist.
# K3s automatically applies any manifests placed here on startup.
# https://docs.k3s.io/installation/packaged-components#auto-deploying-manifests-addons
if [ -d /opt/k3s/manifests ] && [ "$(ls -A /opt/k3s/manifests 2>/dev/null)" ]; then
    mkdir -p /var/lib/rancher/k3s/server/manifests/
    cp /opt/k3s/manifests/* /var/lib/rancher/k3s/server/manifests/
fi

# The `-v 0` option doesn't seem to be working, so we're using grep to filter out info logs
# otherwise there's too much noise in the logs
k3s server ${EXTRA_K3S_SERVER_ARGS:-} 2>&1 | grep -v level=info | egrep -v '^I[[:digit:]]+ '
