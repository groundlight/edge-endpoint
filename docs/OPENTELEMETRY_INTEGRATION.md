# Logging Integration for Edge Endpoint

This document describes the logging options available for the Groundlight Edge Endpoint, including OpenTelemetry integration with Splunk.

## Architecture

The Edge Endpoint uses OpenTelemetry Collector as a sidecar container to collect and forward logs to Splunk:

```
┌─────────────────────────────────────────────────────────────┐
│ Edge Endpoint Pod                                           │
│                                                             │
│ ┌─────────────────┐    ┌─────────────────────────────────┐ │
│ │ App Containers  │    │ OpenTelemetry Collector         │ │
│ │                 │    │                                 │ │
│ │ • edge-endpoint │───▶│ • Reads logs from /var/log/pods │ │
│ │ • status-monitor│    │ • Enriches with K8s metadata   │ │
│ │ • escalation... │    │ • Adds resource attributes      │ │
│ │ • model-updater │    │ • Batches and forwards to Splunk│ │
│ │                 │    │                                 │ │
│ │ (logs to stdout)│    │                                 │ │
│ └─────────────────┘    └─────────────────────────────────┘ │
│                                   │                         │
└───────────────────────────────────┼─────────────────────────┘
                                    │
                                    ▼
                            ┌─────────────────┐
                            │ Splunk HEC      │
                            │ (HTTP Event     │
                            │  Collector)     │
                            └─────────────────┘
```

## Key Features

### ✅ **Automatic Kubernetes Metadata Enrichment**
Every log entry is automatically enriched with:
- `k8s.pod.name` - Pod name (e.g., `edge-endpoint-785749db77-x4ftv`)
- `k8s.deployment.name` - Deployment name (e.g., `edge-endpoint`)  
- `k8s.namespace.name` - Namespace (e.g., `default`)
- `k8s.node.name` - Node name (e.g., `lw-5cg4391bg9`)
- `k8s.container.name` - Container name (e.g., `edge-endpoint`, `status-monitor`)
- Plus labels and annotations as configured

### ✅ **Zero Application Code Changes**
- Applications simply log to stdout/stderr using standard Python logging
- No Splunk-specific imports or configuration needed in app code
- Clean separation of concerns

### ✅ **Resilient Logging**
- OTel Collector handles batching, retries, and connection failures
- Logs are buffered during Splunk outages
- No risk of application crashes due to logging issues

### ✅ **Performance Optimized**
- Efficient log collection using native Kubernetes log paths
- Batching and compression to minimize network overhead
- Configurable resource limits

## Logging Modes

The Edge Endpoint supports three logging modes:

### 1. **Standard Mode** (Default)
Basic logging to stdout and files with no external dependencies.

```bash
helm upgrade -i edge-endpoint /path/to/chart \
  --set loggingMode="standard"
```

### 2. **Local Splunk Mode**
Deploys a local Splunk container alongside your application with OpenTelemetry collection.

```bash
helm upgrade -i edge-endpoint /path/to/chart \
  --set loggingMode="local-splunk"
```

**Features:**
- Local Splunk Enterprise container
- OpenTelemetry Collector sidecar
- Automatic Kubernetes metadata enrichment
- Splunk Web UI accessible at `http://localhost:30080`
- Default credentials: `admin` / `admin123`

### 3. **Cloud Splunk Mode** 
Uses external Splunk instance with OpenTelemetry collection.

```bash
helm upgrade -i edge-endpoint /path/to/chart \
  --set loggingMode="cloud-splunk" \
  --set splunk.cloud.endpoint="https://your-splunk.com:8088/services/collector" \
  --set splunk.cloud.token="your-hec-token"
```

**Note:** This mode requires additional configuration and is currently in development.

## Configuration Reference

### Local Splunk Configuration

```yaml
loggingMode: "local-splunk"
splunk:
  local:
    password: "admin123"
    hecToken: "abcd1234-5678-90ef-ghij-klmnopqrstuv"
    service:
      webNodePort: 30080    # Splunk Web UI
      hecNodePort: 30088    # HTTP Event Collector
    persistence:
      dataSize: "10Gi"
      etcSize: "2Gi"
    resources:
      limits:
        cpu: 2000m
        memory: 4Gi
```

### Cloud Splunk Configuration

```yaml
loggingMode: "cloud-splunk"
splunk:
  cloud:
    endpoint: "https://your-splunk-instance:8088/services/collector"
    token: "your-hec-token-here"
```

## Usage

### Application Logging

Applications use standard Python logging - no changes needed:

```python
import logging

logger = logging.getLogger(__name__)

# These logs will automatically be enriched and sent to Splunk
logger.info("Processing image query", extra={
    "detector_id": "det_123",
    "request_id": "req_456"
})
```

### Sample Log Entry in Splunk

```json
{
  "timestamp": "2025-09-22T10:30:15.123Z",
  "message": "Processing image query",
  "level": "INFO",
  "logger": "app.api.routes.image_queries",
  "detector_id": "det_123",
  "request_id": "req_456",
  "k8s.pod.name": "edge-endpoint-785749db77-x4ftv",
  "k8s.deployment.name": "edge-endpoint",
  "k8s.namespace.name": "default", 
  "k8s.container.name": "edge-endpoint",
  "k8s.node.name": "lw-5cg4391bg9",
  "service.name": "edge-endpoint",
  "deployment.environment": "edge"
}
```

## Troubleshooting

### Check OTel Collector Status

```bash
# Check if OTel collector is running
kubectl get pods -l app=edge-endpoint
kubectl logs <pod-name> -c otel-collector

# Check OTel configuration
kubectl get configmap otel-collector-config -o yaml
```

### Enable Debug Output

Uncomment the debug exporter in the OTel configuration:

```yaml
# In otel-configmap.yaml
service:
  pipelines:
    logs:
      receivers: [filelog]
      processors: [k8sattributes, resource, batch]
      exporters: [splunk_hec, debug]  # Add debug here
```

### Common Issues

1. **No logs appearing in Splunk**
   - Verify HEC token and endpoint are correct
   - Check OTel collector logs for connection errors
   - Ensure Splunk HEC is enabled and reachable

2. **Missing Kubernetes metadata**
   - Verify RBAC permissions are applied
   - Check that OTel collector can access Kubernetes API

3. **High resource usage**
   - Adjust batch size and timeout in OTel config
   - Increase resource limits if needed

## Comparing to Previous HTTP Handler Approach

| Aspect | HTTP Handler (Old) | OpenTelemetry (New) |
|--------|-------------------|-------------------|
| **App Code Changes** | Required imports, custom logger setup | None - standard logging |
| **Kubernetes Metadata** | Manual `component` field only | Automatic rich metadata |
| **Resilience** | App crashes if Splunk unavailable | Robust buffering and retries |
| **Performance** | HTTP requests from app threads | Optimized collector sidecar |
| **Maintenance** | Splunk logic in every app | Centralized in OTel config |
| **Container Coverage** | Python apps only | All containers (nginx, etc.) |

## For Local Development

For local development without Splunk, use standard mode:

```yaml
loggingMode: "standard"
```

Logs will continue to work normally via stdout and file handlers.

## Quick Start Examples

### Local Development (No Splunk)
```bash
helm upgrade -i edge-endpoint ./chart --set loggingMode="standard"
```

### Local Testing with Splunk
```bash
helm upgrade -i edge-endpoint ./chart --set loggingMode="local-splunk"
# Access Splunk Web UI at http://localhost:30080 (admin/admin123)
```

### Production with External Splunk
```bash
# Note: cloud-splunk mode is still in development
helm upgrade -i edge-endpoint ./chart \
  --set loggingMode="cloud-splunk" \
  --set splunk.cloud.endpoint="https://your-splunk.com:8088/services/collector" \
  --set splunk.cloud.token="your-token"
```
