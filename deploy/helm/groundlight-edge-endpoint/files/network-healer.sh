#!/bin/sh
set -eu

log() {
  echo "network-healer: $*"
}

CHECK_INTERVAL_SECONDS="${CHECK_INTERVAL_SECONDS:-5}"
CHROOT="/bin/busybox chroot"
KCTL="$CHROOT /host /usr/local/bin/kubectl"
API_VIP="${KUBERNETES_SERVICE_HOST:-10.43.0.1}"
PERSIST_DIR="${PERSIST_DIR:-/opt/groundlight/edge/healer}"
HOST_IP_FILE="${HOST_IP_FILE:-$PERSIST_DIR/host_ip}"

get_coredns_ready() {
  $KCTL -n kube-system get deploy coredns -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo ""
}

api_vip_reachable() {
  nc -z -w 2 "${API_VIP}" 443 >/dev/null 2>&1
}

resolve_host_ip() {
  $CHROOT /host ip -4 route get 1.1.1.1 2>/dev/null | awk '/src/ {for(i=1;i<=NF;i++) if ($i=="src") print $(i+1)}'
}

is_valid_ip() {
  ip="$1"
  [ -n "$ip" ] && printf "%s" "$ip" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'
}

restart_k3s() {
  $CHROOT /host /bin/sh -c 'systemctl restart k3s || systemctl restart k3s-agent' || true
}

get_health_metrics() {
    coredns="$(get_coredns_ready)"; coredns="${coredns:-0}"
    if api_vip_reachable; then
      vip_status="Reachable"
    else
      vip_status="Unreachable"
    fi
    host_ip="$(resolve_host_ip)"; host_ip="${host_ip:-unknown}"
    echo "CoreDNS readyReplicas=${coredns} | API VIP=${vip_status}(${API_VIP}) | host_ip=${host_ip}"
}

system_healthy() {
  coredns="$(get_coredns_ready)"; coredns="${coredns:-0}"
  [ "$coredns" = "1" ] && api_vip_reachable
}

log "Monitor started (interval=${CHECK_INTERVAL_SECONDS}s)."
while true; do
  previous_host_ip="$(cat "$HOST_IP_FILE" 2>/dev/null || true)"
  host_ip="$(resolve_host_ip)"; host_ip="${host_ip:-unknown}"
  
  # Persist current host IP
  mkdir -p "$PERSIST_DIR" 2>/dev/null || true
  if is_valid_ip "$host_ip"; then
    printf "%s" "$host_ip" > "$HOST_IP_FILE" 2>/dev/null || true
  fi

  # If the host IP changed, log and restart k3s.
  # Also log the health metrics. We won't take action on the health metrics for now, but they might be useful. 
  if ! is_valid_ip "$host_ip"; then
    log "Host IP is invalid or unavailable (${host_ip}). System appears offline; taking no action."
  elif [ -n "${previous_host_ip:-}" ] && [ "$previous_host_ip" != "$host_ip" ]; then
    log "Host IP changed: ${previous_host_ip} -> ${host_ip}."
    log "System health $(system_healthy && echo healthy || echo unhealthy)"
    log "Health metrics: $(get_health_metrics)"
    log "Restarting k3s..."
    restart_k3s
    log "Requested k3s restart on host as a result of host IP address change. Waiting for system to recover..."

    # Poll until healthy or timeout
    health_polling_timeout_sec="120"
    start_ts="$(date +%s)"
    while ! system_healthy; do
      if [ $(( $(date +%s) - start_ts )) -ge "$health_polling_timeout_sec" ]; then
        log "Recovery timed out after ${health_polling_timeout_sec}s. $(get_health_metrics)"
        break
      fi
      sleep 5
    done
    if system_healthy; then
      log "Recovery complete. $(get_health_metrics)"
    fi
  fi

  sleep "$CHECK_INTERVAL_SECONDS"
done