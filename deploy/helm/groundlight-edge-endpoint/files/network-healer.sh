#!/bin/sh
set -eu

CHECK_INTERVAL_SECONDS="${CHECK_INTERVAL_SECONDS:-30}"
FAIL_CONSECUTIVE="${FAIL_CONSECUTIVE:-3}"

# Use host kubectl if available (inside chroot later)
HOST_KUBECTL_CMD="/bin/busybox chroot /host /usr/local/bin/kubectl"
# Use busybox chroot inside the container to execute host commands
HOST_CHROOT_CMD="/bin/busybox chroot"

log() {
  echo "network-healer: $*"
}

host_log() {
  # Also log to the host journal if available, so logs survive apiserver restarts
  if [ -x "/usr/bin/chroot" ] && [ -x "/host/usr/bin/logger" ]; then
    /usr/bin/chroot /host /usr/bin/logger -t network-healer "$*"
  fi
  log "$*"
}

get_apiserver_svc_ip() {
  # Try to get the kubernetes service ClusterIP from the host kubectl
  if [ -x "/usr/bin/chroot" ] && [ -x "/host/usr/local/bin/kubectl" ]; then
    ip="$($HOST_KUBECTL_CMD -n default get svc kubernetes -o jsonpath='{.spec.clusterIP}' 2>/dev/null || true)"
    if [ -n "${ip:-}" ]; then
      echo "$ip"
      return 0
    fi
  fi
  # Fallback to default k3s service CIDR first IP
  echo "10.43.0.1"
}

apiserver_reachable() {
  svc_ip="$(get_apiserver_svc_ip)"
  nc -z -w2 "$svc_ip" 443 >/dev/null 2>&1
}

restart_k3s_on_host() {
  # shellcheck disable=SC2086
  $HOST_CHROOT_CMD /host /bin/sh -c 'systemctl restart k3s || systemctl restart k3s-agent' || true
  host_log "k3s restart command executed on host (via $HOST_CHROOT_CMD)"
}

wait_for_api() {
  if [ -x "/usr/bin/chroot" ] && [ -x "/host/usr/local/bin/kubectl" ]; then
    i=0
    while [ $i -lt 45 ]; do
      if $HOST_KUBECTL_CMD get nodes >/dev/null 2>&1; then
        return 0
      fi
      sleep 2
      i=$((i+1))
    done
  fi
  return 1
}

bounce_coredns() {
  if [ -x "/usr/bin/chroot" ] && [ -x "/host/usr/local/bin/kubectl" ]; then
    $HOST_KUBECTL_CMD -n kube-system delete pod -l k8s-app=kube-dns --ignore-not-found=true >/dev/null 2>&1 || true
    host_log "CoreDNS bounce issued (deleted kube-dns pods)"
  fi
}

host_log "network-healer started (interval=${CHECK_INTERVAL_SECONDS}s, failConsecutive=${FAIL_CONSECUTIVE})"

fails=0
while true; do
  if apiserver_reachable; then
    # Optionally ensure CoreDNS is Ready; if not, bounce it
    if [ -x "/usr/bin/chroot" ] && [ -x "/host/usr/local/bin/kubectl" ]; then
      ready="$($HOST_KUBECTL_CMD -n kube-system get deploy coredns -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo 0)"
      if [ "${ready:-0}" = "0" ]; then
        host_log "CoreDNS not ready; bouncing pods"
        bounce_coredns
      fi
    fi
    if [ "$fails" -gt 0 ]; then
      host_log "apiserver Service reachable again; reset fail counter from $fails"
    fi
    fails=0
  else
    fails=$((fails+1))
    svc_ip="$(get_apiserver_svc_ip)"
    host_log "apiserver Service $svc_ip:443 not reachable (fail $fails/$FAIL_CONSECUTIVE)"
    if [ "$fails" -ge "$FAIL_CONSECUTIVE" ]; then
      host_log "restarting k3s on host"
      restart_k3s_on_host
      if wait_for_api; then
        host_log "API up; bouncing CoreDNS"
        bounce_coredns
      else
        host_log "API did not come up within timeout"
      fi
      fails=0
    fi
  fi
  sleep "$CHECK_INTERVAL_SECONDS"
done


