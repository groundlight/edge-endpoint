# Status Page Dev Tools

Development environment for iterating on the status page frontend with mock data.

## Quick Start

```bash
./run-dev.sh
```

This starts three servers:

| Server | Port | Description |
|--------|------|-------------|
| Vite dev server | 3000 | Status page with hot reload at `http://localhost:3000/status/` |
| Mock data server | 3001 | Serves synthetic `/status/resources.json` and `/status/metrics.json` |
| Mock control panel | 3002 | Web UI to adjust detector count, loading state, and eviction threshold |

Ctrl-C stops all servers.

## Remote machines

If developing over SSH, forward ports 3000 and 3002:

```bash
ssh -L 3000:localhost:3000 -L 3002:localhost:3002 <host>
```

## Pointing at real data

To run the dev server against a live edge endpoint instead of mock data:

```bash
cd ../frontend && npx vite --host
```

(Without `MOCK=1`, Vite proxies to `localhost:30101` by default.)
