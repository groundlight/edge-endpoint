# Toxiproxy for manual outage simulation

Opt-in tools to simulate network impairment between the Edge Endpoint (EE) and the Groundlight cloud. These scripts do NOT modify Helm templates; they operate with `kubectl` against a running cluster and are fully reversible.

Requirements:
- So far, only tested on Ubuntu 22 - but no reason to think it can't work on other versions
- `kubectl` configured to the target cluster
- `DEPLOYMENT_NAMESPACE` set (e.g., `export DEPLOYMENT_NAMESPACE=edge`)

## Install and route EE egress through Toxiproxy

```bash
export DEPLOYMENT_NAMESPACE=edge

# Deploy toxiproxy and route api.groundlight.ai via ClusterIP using hostAliases
./load-testing/toxiproxy/enable_toxiproxy.sh
```

This will:
- Create a `toxiproxy` Deployment and Service in `${DEPLOYMENT_NAMESPACE}`
- Create a proxy named `api_groundlight_ai` listening on `10443` and upstreaming to `api.groundlight.ai:443`
- Patch the `edge-endpoint` Deployment with `hostAliases` mapping `api.groundlight.ai` to the Toxiproxy Service ClusterIP, affecting all containers (nginx, edge-endpoint, status-monitor, inference-model-updater)

## Add fixed latency

```bash
# Add 1500ms latency (no jitter), downstream only (default)
./load-testing/toxiproxy/enable_latency.sh 1500

# Add 1000ms latency with 200ms jitter, downstream (explicit)
./load-testing/toxiproxy/enable_latency.sh 1000 --jitter 200 --direction down

# Add bidirectional latency
./load-testing/toxiproxy/enable_latency.sh 2000 --direction both
```

## Remove latency

```bash
./load-testing/toxiproxy/disable_latency.sh
```

## Disable Toxiproxy and restore normal routing

```bash
./load-testing/toxiproxy/disable_toxiproxy.sh
```

## Simulate total outage

Two modes:
- refuse: disable proxy so connections are refused immediately (RST)
- blackhole: add timeout toxics so connections hang for a duration

```bash
# Refuse connections (default)
./load-testing/toxiproxy/enable_outage.sh --mode refuse

# Blackhole connections for 30s (hang)
./load-testing/toxiproxy/enable_outage.sh --mode blackhole --blackhole-ms 30000

# Disable outage (re-enable proxy and remove timeout toxics)
./load-testing/toxiproxy/disable_outage.sh
```

Notes:
- All egress to `api.groundlight.ai` is intercepted. Other cloud calls may be indirectly affected if the EE relies on cloud APIs behind this hostname.
- Scripts are idempotent where possible. If you already created the proxy, the enable script updates it.
- Latency toxic is applied on the upstream stream (toward cloud). You can adjust or extend scripts to add bandwidth, timeout, or outage toxics similarly via the Toxiproxy admin API (`:8474`).
