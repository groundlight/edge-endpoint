#!/bin/bash
set -euo pipefail

# Install a NetworkManager dispatcher hook that restarts k3s on network/IP changes.
# This script runs in a Helm post-install/upgrade Job chrooted to the host (/).

HOOK_DIR="/etc/NetworkManager/dispatcher.d"
HOOK_PATH="${HOOK_DIR}/99-k3s-restart"
RECONCILE_BIN="/usr/local/bin/edge-ip-reconcile.sh"
RECONCILE_SERVICE="/etc/systemd/system/edge-ip-reconcile.service"
RECONCILE_TIMER="/etc/systemd/system/edge-ip-reconcile.timer"

if [ ! -d "/etc/NetworkManager" ]; then
  echo "NetworkManager not found on host. Skipping k3s network-change hook installation."
  exit 0
fi

mkdir -p "${HOOK_DIR}"
cat > "${HOOK_PATH}" <<"EOF"
#!/bin/bash
# Restart k3s (or k3s-agent) on link/DHCP/connectivity changes
IFACE="$1"
ACTION="$2"

log() {
    logger -t k3s-network-hook "iface=${IFACE} action=${ACTION}: $*"
}

restart_service_if_active() {
    local svc="$1"
    if systemctl list-unit-files | grep -q "^${svc}\\.service"; then
        if systemctl is-active --quiet "${svc}"; then
            log "restarting ${svc}"
            systemctl restart "${svc}"
            return $?
        fi
    fi
    return 1
}

case "${ACTION}" in
    up|dhcp4-change|dhcp6-change|carrier|connectivity-change)
        sleep 2
        restart_service_if_active "k3s" || restart_service_if_active "k3s-agent" || {
            log "no active k3s service found to restart"
        }
        ;;
    *)
        ;;
esac
EOF

chmod 0755 "${HOOK_PATH}"
echo "Installed k3s network-change hook at ${HOOK_PATH}"

# Reload NetworkManager if possible to pick up new dispatcher scripts
if systemctl is-active --quiet NetworkManager; then
  systemctl reload NetworkManager || true
fi

# Also install a periodic reconciliation (systemd timer) that ensures k3s is consistent after IP changes.
# This runs even if k8s is temporarily degraded.
cat > "${RECONCILE_BIN}" <<"EOF"
#!/bin/bash
set -euo pipefail

log() {
  logger -t edge-ip-reconcile "$*"
}

# Determine kubectl command
if command -v kubectl >/dev/null 2>&1; then
  K="kubectl"
elif command -v k3s >/dev/null 2>&1; then
  K="k3s kubectl"
else
  log "kubectl not found (and no k3s). Skipping reconcile."
  exit 0
fi

# Get current host primary IP and node InternalIP
HOST_IP="$(ip route get 1.1.1.1 2>/dev/null | awk '{print $7; exit}')"
NODE_IP="$($K get nodes -o custom-columns='INTERNAL-IP:.status.addresses[?(@.type=="InternalIP")].address' --no-headers 2>/dev/null | head -n1)"

if [ -z "${HOST_IP:-}" ] || [ -z "${NODE_IP:-}" ]; then
  log "Unable to determine HOST_IP (${HOST_IP:-unset}) or NODE_IP (${NODE_IP:-unset}); skipping."
  exit 0
fi

if [ "${HOST_IP}" != "${NODE_IP}" ]; then
  log "Detected node IP mismatch host=${HOST_IP} node=${NODE_IP}; restarting k3s services."
  if systemctl is-active --quiet k3s; then
    systemctl restart k3s || true
  elif systemctl is-active --quiet k3s-agent; then
    systemctl restart k3s-agent || true
  else
    log "No active k3s service to restart."
    exit 0
  fi
else
  # Also handle case where kube-proxy/CNI rules might be stale even if IPs match.
  # If NodePort 30101 is not responding locally, poke k3s.
  if ! timeout 2 bash -c "</dev/tcp/127.0.0.1/30101" 2>/dev/null; then
    log "NodePort 30101 not listening on localhost; restarting k3s to refresh kube-proxy/CNI."
    if systemctl is-active --quiet k3s; then
      systemctl restart k3s || true
    elif systemctl is-active --quiet k3s-agent; then
      systemctl restart k3s-agent || true
    fi
  fi
fi
EOF
chmod 0755 "${RECONCILE_BIN}"
echo "Installed reconcile script at ${RECONCILE_BIN}"

cat > "${RECONCILE_SERVICE}" <<"EOF"
[Unit]
Description=Groundlight Edge - IP/state reconciliation
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/edge-ip-reconcile.sh
EOF

cat > "${RECONCILE_TIMER}" <<"EOF"
[Unit]
Description=Run Groundlight Edge IP/state reconciliation periodically

[Timer]
OnBootSec=1m
OnUnitActiveSec=2m
AccuracySec=30s
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload || true
systemctl enable --now edge-ip-reconcile.timer || true
echo "Enabled systemd timer edge-ip-reconcile.timer"


