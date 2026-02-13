#!/bin/sh
set -eu

log() {
  echo "network-healer: $*"
}

CHECK_INTERVAL_SECONDS="${CHECK_INTERVAL_SECONDS:-5}"
CHROOT="/bin/busybox chroot"
# Explicitly use the k3s kubeconfig so the healer always talks to the local
# cluster, even if the host has multiple kubeconfig contexts configured.
KCTL="$CHROOT /host /usr/local/bin/kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml"
API_VIP="${KUBERNETES_SERVICE_HOST:-10.43.0.1}"
PERSIST_DIR="${PERSIST_DIR:-/opt/groundlight/edge/healer}"
HOST_IP_FILE="${HOST_IP_FILE:-$PERSIST_DIR/host_ip}"
KCTL_TIMEOUT_SECONDS="${KCTL_TIMEOUT_SECONDS:-5}"
VIP_TIMEOUT_SECONDS="${VIP_TIMEOUT_SECONDS:-3}"
TIMEOUT_BIN="${TIMEOUT_BIN:-/bin/busybox timeout}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-6s}"

get_coredns_ready() {
  $TIMEOUT_BIN -k 1s "$HEALTH_TIMEOUT" \
    $KCTL --request-timeout="${KCTL_TIMEOUT_SECONDS}s" \
    -n kube-system get deploy coredns -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo ""
}

api_vip_reachable() {
  $TIMEOUT_BIN -k 1s "${VIP_TIMEOUT_SECONDS}s" \
    nc -z -w "${VIP_TIMEOUT_SECONDS}" "${API_VIP}" 443 >/dev/null 2>&1
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
  [ "$coredns" -ge 1 ] && api_vip_reachable
}

log "Monitor started (interval=${CHECK_INTERVAL_SECONDS}s)."
last_offline=""
while true; do
  previous_host_ip="$(cat "$HOST_IP_FILE" 2>/dev/null || true)"
  host_ip="$(resolve_host_ip)"; host_ip="${host_ip:-unknown}"
  
  # Persist current host IP
  mkdir -p "$PERSIST_DIR" 2>/dev/null || true
  if is_valid_ip "$host_ip"; then
    printf "%s" "$host_ip" > "$HOST_IP_FILE" 2>/dev/null || true
  fi

  # Track offline/online transitions to avoid repeated logs
  if is_valid_ip "$host_ip"; then
    current_offline="0"
  else
    current_offline="1"
  fi
  if [ -n "$last_offline" ] && [ "$last_offline" != "$current_offline" ]; then
    if [ "$current_offline" = "1" ]; then
      log "Host IP is invalid or unavailable (${host_ip}). System appears offline; taking no action."
    else
      log "System is back online at ${host_ip}."
    fi
  fi
  last_offline="$current_offline"

  # While offline, skip any heal actions
  if [ "$current_offline" = "1" ]; then
    sleep "$CHECK_INTERVAL_SECONDS"
    continue
  fi

  # If the host IP changed, log and restart k3s. Also log health metrics.
  if [ -n "${previous_host_ip:-}" ] && [ "$previous_host_ip" != "$host_ip" ]; then
    log "Host IP changed: ${previous_host_ip} -> ${host_ip}."
    log "System health $(system_healthy && echo healthy || echo unhealthy)"
    log "Health metrics: $(get_health_metrics)"
    log "Restarting k3s..."
    restart_k3s
    log "Requested k3s restart on host as a result of host IP address change. Waiting for system to recover..."

    # Poll until healthy or timeout with progress logs
    sleep 10
    health_polling_timeout_sec="180"
    start_ts="$(date +%s)"
    while :; do
      elapsed=$(( $(date +%s) - start_ts ))
      if system_healthy; then
        log "Recovery complete. $(get_health_metrics)"
        break
      fi
      if [ "$elapsed" -ge "$health_polling_timeout_sec" ]; then
        log "Recovery timed out after ${health_polling_timeout_sec}s. $(get_health_metrics)"
        break
      fi
      log "Recovering... elapsed=${elapsed}s $(get_health_metrics)"
      sleep 5
    done
  fi

  sleep "$CHECK_INTERVAL_SECONDS"
done