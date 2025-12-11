#!/bin/sh
set -eu

# Simple network healer:
# - If CoreDNS is NotReady, restart k3s on the host.
# - Loop every CHECK_INTERVAL_SECONDS.

CHECK_INTERVAL_SECONDS="${CHECK_INTERVAL_SECONDS:-10}"
CHROOT="/bin/busybox chroot"
KCTL="$CHROOT /host /usr/local/bin/kubectl"

log() {
  echo "network-healer: $*"
}

get_coredns_ready() {
  $KCTL -n kube-system get deploy coredns -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo ""
}

restart_k3s() {
  $CHROOT /host /bin/sh -c 'systemctl restart k3s || systemctl restart k3s-agent' || true
  log "Requested k3s restart on host. Waiting for CoreDNS to recover..."
}

log "Starting (interval=${CHECK_INTERVAL_SECONDS}s). Will restart k3s if CoreDNS is NotReady."

last_status="unknown"
while true; do
  ready="$(get_coredns_ready)"
  ready="${ready:-0}"

  if [ "$ready" = "0" ]; then
    if [ "$last_status" != "unready" ]; then
      log "CoreDNS is NotReady (readyReplicas=0). Triggering k3s restart..."
    else
      log "CoreDNS still NotReady. Triggering k3s restart again..."
    fi
    restart_k3s
    last_status="unready"
  else
    if [ "$last_status" = "unready" ]; then
      log "CoreDNS recovered after k3s restart and is now Ready (readyReplicas=${ready})."
    elif [ "$last_status" != "ready" ]; then
      log "CoreDNS is Ready (readyReplicas=${ready})."
    fi
    last_status="ready"
  fi

  sleep "$CHECK_INTERVAL_SECONDS"
done


