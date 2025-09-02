# Using Toxiproxy for network failure testing

Toxiproxy is a programmable network proxy for simulating network conditions (latency, timeouts, outages) between services. In the edge endpoint deployment, these scripts deploy a Toxiproxy instance in your Kubernetes namespace and patch the `edge-endpoint` Deployment to route `api.groundlight.ai` traffic through Toxiproxy. This allows you to introduce controlled impairments for testing resilience and behavior under failure.

- Admin API: Toxiproxy exposes an HTTP admin API on port 8474 used by these scripts.
- Routing: The scripts create a proxy `api_groundlight_ai` listening on 10443 and upstreaming to `api.groundlight.ai:443`. A `hostAliases` patch points `api.groundlight.ai` to the Toxiproxy Service IP so all containers in the `edge-endpoint` pod route through it.
- Access: Scripts use a temporary `kubectl port-forward` to call the in-cluster admin API. No ports are exposed outside the cluster.

For general info on Toxiproxy, see [the source repo](https://github.com/Shopify/toxiproxy/tree/main).

## Prerequisites

- A working Kubernetes cluster and `kubectl` configured to the target context.
- A deployed edge endpoint in the target namespace.
- Poetry environment with project dependencies installed
- Environment variable `DEPLOYMENT_NAMESPACE` set to your namespace. Example:

```bash
export DEPLOYMENT_NAMESPACE=edge
```

## Enabling Toxiproxy

1) Enable Toxiproxy in your namespace (deploys resources, creates/updates the proxy, patches the deployment):

```bash
poetry run python enable_toxiproxy.py
```

2) Disable Toxiproxy (deleting the created resources) and restore normal routing:

```bash
poetry run python disable_toxiproxy.py
```

Notes:
- `enable_toxiproxy.py` is idempotent and will update the proxy if it already exists.

## Checking Status

To check the status, which includes whether the proxy is enabled and any active toxics:

```bash
poetry run python status.py
```

## Latency functionality

Add fixed latency (with optional jitter) to the proxy. Direction refers to the Toxiproxy stream relative to the client:
- `up` → upstream (from EE → cloud)
- `down` → downstream (from cloud → EE)
- `both` → both directions

Examples:

```bash
# Add 1500ms upstream latency (default direction is 'up')
poetry run python enable_latency.py 1500

# Add 1000ms upstream latency with 200ms jitter
poetry run python enable_latency.py 1000 --jitter 200 --direction up

# Add bidirectional latency of 2000ms
poetry run python enable_latency.py 2000 --direction both
```

Remove latency toxics:

```bash
poetry run python disable_latency.py
```

Behavior details:
- If a latency toxic already exists (HTTP 409), the script will update its attributes and inform you.

## Timeout functionality

Add timeout toxics so connections hang up to a configured duration. You can target upstream (EE → cloud), downstream (cloud → EE), or both directions.

Examples:

```bash
# Enable 30s timeout on both streams (default)
poetry run python enable_timeout.py --timeout-ms 30000 --timeout-stream both

# Enable 10s timeout only on upstream traffic
poetry run python enable_timeout.py --timeout-ms 10000 --timeout-stream up
```

Disable timeout (re-enable proxy and remove timeout toxics):

```bash
poetry run python disable_timeout.py
```

Behavior details:
- If a timeout toxic already exists (HTTP 409), the script will update its attributes and inform you.

## Outage functionality

Refuse all connections by disabling the proxy (RST).

Examples:

```bash
# Refuse connections (disable the proxy)
poetry run python enable_outage.py
```

Disable outage (re-enable proxy):

```bash
poetry run python disable_outage.py
```

## Flap impairment functionality

Continuously alternate between UP (normal) and DOWN (impairment) periods. Supports:
- `refuse` (disable proxy)
- `timeout` (add/remove timeout toxics)

Arguments:
- `--mode` refuse|timeout (default: timeout)
- `--up-ms` milliseconds the connection stays healthy each cycle (default: 15000)
- `--down-ms` milliseconds the impairment lasts each cycle (default: 15000)
- `--timeout-ms` timeout used during timeout DOWN periods (default: 30000)
- `--timeout-stream` up|down|both for timeout mode (default: both)
- `--iterations` number of cycles to run, where a cycle is one up period and one down period; 0 means run until manually stopped (default: 0)

Examples:

```bash
# Flap timeout: 10s up, 5s down, 20s timeout, upstream only
poetry run python flap_impairment.py \
  --mode timeout --up-ms 10000 --down-ms 5000 --timeout-ms 20000 --timeout-stream up

# Flap refuse for 5 cycles, 5s up / 5s down
poetry run python flap_impairment.py \
  --mode refuse --up-ms 5000 --down-ms 5000 --iterations 5
```

Behavior details:
- During UP periods, timeout toxics are removed (for timeout mode) or the proxy is enabled (for refuse mode).
- During DOWN periods, timeout toxics are added (timeout) or the proxy is disabled (refuse).
- Use Ctrl+C to stop; the script cleans up on exit.

## Troubleshooting

- “Namespace does not exist…”
  - Create the namespace first, or set `DEPLOYMENT_NAMESPACE` correctly.

- “Toxiproxy is not installed…”
  - Run `enable_toxiproxy.py` first in the target namespace.

- “Failed to disable/enable proxy…”
  - Ensure `kubectl` can access the cluster and there are no network policies blocking pod-to-pod communication.

- Local port-forward conflicts
  - If port 8474 is in use locally, close the process or modify the scripts to use a different local port.


