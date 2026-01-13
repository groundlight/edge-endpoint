## Unused network hooks (archived experiment)

This directory contains an experimental approach for restarting k3s when the host network changes (for example, DHCP/IP changes). It is not used by the main deployment.

### Contents

- **NetworkManager dispatcher hook**
  - `deploy/bin/hooks/99-k3s-restart.sh`: NetworkManager dispatcher script that restarts `k3s` or `k3s-agent` on link/DHCP/connectivity changes.
  - `deploy/bin/install-k3s-network-change-hook.sh`: Installs the dispatcher script on a host (requires NetworkManager).

- **Helm post-install/upgrade installer Job**
  - `deploy/helm/groundlight-edge-endpoint/templates/_network-change-hook.yaml`: Helm Job template that would install the hook on the host. The leading `_` keeps it inactive (Helm does not render underscore-prefixed templates).
  - `deploy/helm/groundlight-edge-endpoint/files/install-network-hook.sh`: Script embedded by the Job. Installs the dispatcher hook and a small systemd timer (`edge-ip-reconcile.timer`) that periodically reconciles node/host IP state.

### How to re-enable (if this approach is revisited)

- **Manual host install**: run `deploy/bin/install-k3s-network-change-hook.sh` on a host that uses NetworkManager.
- **Helm-based install**:
  - Move the archived template/script back under `deploy/helm/groundlight-edge-endpoint/`.
  - Rename the template to remove the leading underscore so Helm renders it.
  - Add an explicit values gate (for example `networkChangeHook.enabled`) so it can be turned on/off intentionally.

