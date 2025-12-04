#!/bin/bash

# NetworkManager dispatcher script to restart k3s (or k3s-agent) on network changes.
# Place at: /etc/NetworkManager/dispatcher.d/99-k3s-restart (executable)
#
# NM Dispatcher calls: <script> <interface> <action>
# Actions commonly include: up, down, dhcp4-change, dhcp6-change, carrier, connectivity-change

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
        # Allow DHCP to settle briefly to avoid flapping
        sleep 2
        # Prefer restarting the active k3s role on this node
        restart_service_if_active "k3s" || restart_service_if_active "k3s-agent" || {
            log "no active k3s service found to restart"
        }
        ;;
    *)
        # Ignore other actions
        ;;
esac



