Toxiproxy toggle (no chart edits)

These scripts deploy Toxiproxy next to the Edge Endpoint and patch the running Deployment to map `api.groundlight.ai` to the Toxiproxy Service IP using `hostAliases`. This preserves TLS/SNI and avoids editing your Helm chart.

Enable:
```bash
# args: <namespace> <ee-deployment-name> <cloud-host>
bash load-testing/toxiproxy/enable_toxiproxy.sh edge edge-endpoint api.groundlight.ai
```

Disable:
```bash
bash load-testing/toxiproxy/disable_toxiproxy.sh edge edge-endpoint api.groundlight.ai
```

Add chaos via admin API (example):
```bash
kubectl -n edge port-forward svc/toxiproxy 8474:8474

# 45s downstream timeout (intermittent outage you can toggle)
curl -sX POST localhost:8474/proxies/gl/toxics \
  -H 'Content-Type: application/json' \
  -d '{"name":"outage","type":"timeout","stream":"downstream","attributes":{"timeout":45000}}'

# Enable/disable loop
while true; do curl -sX POST localhost:8474/toxics/gl/outage/enable; sleep 30; curl -sX POST localhost:8474/toxics/gl/outage/disable; sleep 30; done
```

Notes
- If the cloud IP changes during a long test, re-run the enable script; it recreates the proxy with the current IP.
- You can add other toxics (latency, jitter, bandwidth, reset_peer) the same way.

