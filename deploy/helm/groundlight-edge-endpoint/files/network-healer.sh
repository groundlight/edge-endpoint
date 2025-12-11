#!/bin/sh
set -eu

# Simple network healer:
# - Restart k3s if either:
#   * CoreDNS is NotReady, OR
#   * the Kubernetes API VIP TCP:443 is unreachable for N consecutive checks.
# - Loop every CHECK_INTERVAL_SECONDS.

CHECK_INTERVAL_SECONDS="${CHECK_INTERVAL_SECONDS:-10}"
CHROOT="/bin/busybox chroot"
KCTL="$CHROOT /host /usr/local/bin/kubectl"
API_VIP="${KUBERNETES_SERVICE_HOST:-10.43.0.1}"

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

api_vip_reachable() { nc -z -w 2 "${API_VIP}" 443 >/dev/null 2>&1; }

log "Starting (interval=${CHECK_INTERVAL_SECONDS}s). Monitoring API VIP ${API_VIP} and CoreDNS."

last_status="unknown"
vip_fail=0
# Number of consecutive VIP failures before triggering a restart
VIP_FAIL_THRESHOLD=2
while true; do
  # 1) Check API VIP reachability (TCP)
  if api_vip_reachable; then
    if [ "$vip_fail" -gt 0 ]; then
      log "API VIP ${API_VIP}:443 is reachable again (was failing ${vip_fail} checks)."
    fi
    vip_fail=0
  else
    vip_fail=$((vip_fail+1))
    log "API VIP ${API_VIP}:443 unreachable (fail ${vip_fail}/${VIP_FAIL_THRESHOLD})."
  fi

  # 2) Check CoreDNS readiness
  ready="$(get_coredns_ready)"
  ready="${ready:-0}"

  if [ "$ready" = "0" ] || [ "$vip_fail" -ge "$VIP_FAIL_THRESHOLD" ]; then
    if [ "$last_status" != "unready" ]; then
      if [ "$ready" = "0" ]; then
        log "CoreDNS is NotReady (readyReplicas=0). Triggering k3s restart..."
      else
        log "API VIP still unreachable after ${vip_fail} checks. Triggering k3s restart..."
      fi
    else
      log "Condition persists (CoreDNS NotReady or VIP unreachable). Triggering k3s restart again..."
    fi
    restart_k3s
    vip_fail=0
    last_status="unready"

    # Give k3s plenty of time to come back up
    k3s_wait_time_sec="60"
    log "Waiting $k3s_wait_time_sec seconds for k3s to restart..."
    sleep "$k3s_wait_time_sec"
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


