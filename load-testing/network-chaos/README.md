Network Chaos Scripts (Linux)

Simple shell scripts to simulate temporary outages against the Groundlight cloud host without modifying the EE deployment.

Scope
- Intended for manual testing on a Linux host where EE or your client runs.
- For EE inside Kubernetes, prefer Toxiproxy or node-level commands run by an operator with privileges.

Temporary outage:
```bash
# Block egress to api.groundlight.ai:443 using iptables (requires sudo)
bash load-testing/network-chaos/enable_outage_linux.sh

# Unblock
bash load-testing/network-chaos/disable_outage_linux.sh
```

Notes
- Uses iptables to DROP outbound TCP 443 to the resolved IP(s) of `api.groundlight.ai`.
- If the cloud IP changes, re-run the enable script.
- For latency/jitter/bandwidth on Linux, consider `tc netem`; scripts can be added similarly, but typically require root and may affect all traffic on an interface.

