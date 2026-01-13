#!/bin/bash
set -euo pipefail

# Installs a NetworkManager dispatcher hook that restarts k3s on network/IP changes.
#
# Usage:
#   sudo ./deploy/bin/install-k3s-network-change-hook.sh
#
# This copies ./deploy/bin/hooks/99-k3s-restart.sh to
# /etc/NetworkManager/dispatcher.d/99-k3s-restart and makes it executable.

require_root() {
    if [ "${EUID:-$(id -u)}" -ne 0 ]; then
        echo "This script must run as root; re-executing with sudo..."
        exec sudo -E "$0" "$@"
    fi
}

main() {
    require_root "$@"

    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    SRC="${SCRIPT_DIR}/hooks/99-k3s-restart.sh"
    DEST_DIR="/etc/NetworkManager/dispatcher.d"
    DEST="${DEST_DIR}/99-k3s-restart"

    if [ ! -f "${SRC}" ]; then
        echo "Source hook not found at ${SRC}"
        exit 1
    fi

    mkdir -p "${DEST_DIR}"
    install -m 0755 "${SRC}" "${DEST}"

    echo "Installed k3s network-change hook to ${DEST}"
    echo "Verify NetworkManager is managing your interfaces and is running:"
    echo "  systemctl status NetworkManager"
    echo "Hook will restart k3s/k3s-agent on link/IP changes."
}

main "$@"



