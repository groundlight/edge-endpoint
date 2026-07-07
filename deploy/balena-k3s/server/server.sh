#!/bin/sh

set -eux

# https://docs.k3s.io/cli/server
# https://docs.k3s.io/datastore/ha-embedded
# https://github.com/balena-io-experimental/balena-k3s/blob/main/server/server.sh


# NOTE: this script is only intended to support a single-node "cluster". Multi-node
# clusters require using ectd as a datastore, instead of the default mysql. Etcd
# doesnt work well when the underlying storage is an sd card, like on raspberry pi.
# If we ever do want multi-node we'd have to pass `--server` or `--cluster-init` args to k3s

# cgroup v2 shim: on hosts using the unified cgroup hierarchy (balenaOS 7.x+),
# the container is started in a private cgroup namespace whose root already
# has controllers enabled in "domain" mode. kubelet then cannot create
# /sys/fs/cgroup/kubepods as a controller cgroup ("cannot enter cgroupv2 ...
# with domain controllers -- it is in an invalid state"), and k3s crash-loops.
# Move PID 1 into a leaf cgroup and enable controllers in the root's
# subtree_control so kubelet can create kubepods alongside it. No-op on
# cgroup v1 hosts.
if [ "$(stat -c %T -f /sys/fs/cgroup 2>/dev/null)" = "cgroup2fs" ]; then
    mkdir -p /sys/fs/cgroup/init
    echo 1 > /sys/fs/cgroup/init/cgroup.procs
    sed -e "s/ / +/g" -e "s/^/+/" < /sys/fs/cgroup/cgroup.controllers \
        > /sys/fs/cgroup/cgroup.subtree_control
fi

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

# balena-engine uses iptables-legacy with a FORWARD DROP policy and only adds
# ACCEPT rules for its own bridges (balena0, supervisor0).  K3s uses
# iptables-nft (ubuntu:22.04 default), so its flannel/kube-proxy rules never
# appear in the legacy tables.  Without explicit legacy ACCEPT rules, all pod
# egress traffic (including DNS from CoreDNS) is silently dropped.
#
# We own the EDGE-FORWARD chain entirely -- flush and rebuild on every startup
# for a guaranteed clean state.  The jump from DOCKER-USER survives
# balena-engine iptables rebuilds because balena-engine never touches
# DOCKER-USER contents.
echo "Setting up iptables-legacy FORWARD rules for k3s networks..."
iptables-legacy -N EDGE-FORWARD 2>/dev/null || true
iptables-legacy -F EDGE-FORWARD
iptables-legacy -A EDGE-FORWARD -s 10.42.0.0/16 -j ACCEPT
iptables-legacy -A EDGE-FORWARD -d 10.42.0.0/16 -j ACCEPT
iptables-legacy -A EDGE-FORWARD -s 10.43.0.0/16 -j ACCEPT
iptables-legacy -A EDGE-FORWARD -d 10.43.0.0/16 -j ACCEPT
iptables-legacy -C DOCKER-USER -j EDGE-FORWARD 2>/dev/null || \
    iptables-legacy -I DOCKER-USER -j EDGE-FORWARD
echo "iptables-legacy rules ready"

# Ensure the root filesystem has shared mount propagation so that k3s pods can use
# mountPropagation: Bidirectional (needed by the mount-s3 FUSE sidecar).
# In Balena, the server container's root is private by default.
mount --make-rshared /

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

# Copy preloaded images to k3s agent images directory for airgap/restricted network support.
# k3s automatically imports tarballs from this directory on startup.
# See: https://docs.k3s.io/installation/airgap
if [ -d /opt/k3s/preload-images ] && [ "$(ls -A /opt/k3s/preload-images 2>/dev/null)" ]; then
    echo "Copying preloaded images to k3s agent images directory..."
    mkdir -p /var/lib/rancher/k3s/agent/images/
    cp /opt/k3s/preload-images/* /var/lib/rancher/k3s/agent/images/
    echo "Preloaded images ready"
fi

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
