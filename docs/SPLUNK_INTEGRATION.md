# Splunk Integration Guide for Edge Endpoint

## Overview

This document describes the Splunk integration for the Edge Endpoint application, providing centralized logging, event management, and advanced analytics capabilities. Splunk complements the existing monitoring by focusing on log aggregation, search, and operational intelligence.

## Architecture

### Integration Components

```
┌─────────────────────────────────────────────────────────────────┐
│                     Edge Endpoint Application                  │
├─────────────┬─────────────────┬──────────────────┬─────────────┤
│Edge Logic  │Status Monitor   │Escalation Queue  │Model Updater│
│(HEC Direct) │(HEC Direct)     │(HEC Direct)      │(HEC Direct) │
└─────┬───────┴─────┬───────────┴────┬─────────────┴─────┬───────┘
      │             │                │                   │
      ▼             ▼                ▼                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                 Splunk HTTP Event Collector                    │
│                        (Port 8088)                             │
└───────────────────────────────┬─────────────────────────────────┘
                                │
      ┌─────────────────────────┼─────────────────────────┐
      ▼                         ▼                         ▼
┌────────────┐          ┌─────────────┐          ┌──────────────┐
│edge_app    │          │edge_events  │          │edge_metrics  │
│  Index     │          │   Index     │          │   Index      │
└────────────┘          └─────────────┘          └──────────────┘
                                │
                    ┌───────────┴───────────┐
                    │   Splunk Web UI       │
                    │   (Port 8000)         │
                    └───────────────────────┘
```

### Data Flow

1. **Application Logs**: All containers use custom Splunk handler to send structured logs via HEC
2. **Event Publishing**: Inference requests, escalations, and model updates sent directly to HEC
3. **Metrics Export**: Performance metrics and system health data sent to Splunk metrics index

## Deployment

### 1. Enable Splunk in Helm Values

Edit your `values.yaml` file:

```yaml
splunk:
  enabled: true  # Enable Splunk deployment
  password: "your-secure-password"
  hecToken: "your-hec-token"
  service:
    type: NodePort
    webNodePort: 30080    # Splunk Web UI
    hecNodePort: 30088    # HTTP Event Collector
  persistence:
    dataSize: "20Gi"      # Adjust based on your needs
    etcSize: "5Gi"
```

### 2. Deploy with Helm

```bash
# Deploy edge endpoint with Splunk enabled
helm upgrade --install edge-endpoint ./deploy/helm/groundlight-edge-endpoint \
  --set splunk.enabled=true \
  --set splunk.password=admin123 \
  --set splunk.hecToken=abcd1234-5678-90ef-ghij-klmnopqrstuv
```

### 3. Access Splunk Web UI

```bash
# Get the node port for Splunk Web UI
kubectl get service splunk -n edge

# Access Splunk at:
# URL: http://<node-ip>:30080
# Username: admin
# Password: admin123 (or your configured password)
```

## Configuration

### Environment Variables

The following environment variables are automatically configured when Splunk is enabled:

```bash
# Splunk Configuration (automatically set by Helm)
SPLUNK_HEC_URL=http://splunk:8088
SPLUNK_HEC_TOKEN=abcd1234-5678-90ef-ghij-klmnopqrstuv
SPLUNK_INDEX=edge_app
```

### Splunk Indexes

The following indexes are automatically created:

| Index | Purpose | Retention |
|-------|---------|-----------|
| `edge_app` | Application logs | 30 days |
| `edge_events` | Inference requests and escalations | 90 days |
| `edge_metrics` | Performance metrics | 7 days |
| `edge_errors` | Error tracking | 30 days |
| `edge_inference` | Inference analytics | 90 days |

## Usage

### Logging Integration

The Edge Endpoint automatically sends logs to Splunk when configured:

```python
from app.utils import loghelper

logger = loghelper.create_logger("my_component")

# Logs are automatically sent to both file and Splunk
logger.info("Processing inference request", extra={
    "detector_id": "det_123",
    "request_id": "req_456"
})
```

### Event Publishing

Example log event structure in Splunk:

```json
{
  "time": 1234567890.123,
  "host": "edge-endpoint-abc123",
  "source": "edge-endpoint",
  "sourcetype": "edge:endpoint:logs",
  "index": "edge_app",
  "event": {
    "message": "Processing inference request",
    "level": "INFO",
    "detector_id": "det_123",
    "request_id": "req_456",
    "component": "edge_logic"
  }
}
```

## Search Queries

### Basic Searches

```spl
# All events from edge endpoint
index=edge_*

# Application logs
index=edge_app

# Inference events
index=edge_events

# Errors across all components
index=edge_app level=ERROR
```

### Advanced Analytics

```spl
# Inference request rate by detector (last hour)
index=edge_app "inference request"
| timechart span=1m count by detector_id

# Error rate trending by component
index=edge_app level=ERROR
| timechart span=5m count by component

# Model update activity
index=edge_app component="model_updater"
| stats count by detector_id

# Escalation patterns
index=edge_app "escalation"
| stats count by detector_id, escalation_reason
```

### Performance Monitoring

```spl
# Processing time analysis
index=edge_app "processing_time"
| stats avg(processing_time_ms) as avg_time,
        max(processing_time_ms) as max_time,
        perc95(processing_time_ms) as p95_time by detector_id

# Memory usage patterns
index=edge_metrics component="system"
| timechart avg(memory_usage_mb) by container_name

# Inference throughput
index=edge_events event_type="inference_complete"
| timechart span=1m count as requests_per_minute
```

## Monitoring Commands

```bash
# Check Splunk pod status
kubectl get pods -n edge -l app.kubernetes.io/component=splunk

# View Splunk logs
kubectl logs -n edge deployment/splunk

# Check HEC health
kubectl exec -n edge deployment/splunk -- \
  curl -s http://localhost:8088/services/collector/health

# Port forward for local access
kubectl port-forward -n edge service/splunk 8000:8000
```

## Troubleshooting

### Common Issues

#### 1. HEC Not Accepting Events

```bash
# Check HEC health from within cluster
kubectl exec -n edge deployment/edge-endpoint -- \
  curl -s http://splunk:8088/services/collector/health

# Verify token
kubectl get configmap splunk-config -n edge -o yaml
```

#### 2. No Events in Splunk

```bash
# Check if Splunk is running
kubectl get pods -n edge -l app.kubernetes.io/component=splunk

# Check edge endpoint logs for Splunk errors
kubectl logs -n edge deployment/edge-endpoint -c edge-logic-server | grep -i splunk
```

#### 3. Connection Errors

```bash
# Check service discovery
kubectl get service splunk -n edge

# Test connectivity between pods
kubectl exec -n edge deployment/edge-endpoint -- \
  nslookup splunk
```

### Storage Issues

```bash
# Check PVC status
kubectl get pvc -n edge | grep splunk

# Monitor storage usage
kubectl exec -n edge deployment/splunk -- df -h
```

## Best Practices

### 1. Structured Logging

Always use structured fields for better searchability:

```python
logger.info("Event occurred", extra={
    "detector_id": detector_id,
    "component": "edge_logic",
    "request_id": request_id,
    "confidence": 0.95
})
```

### 2. Index Management

- Use appropriate indexes for different data types
- Set retention policies based on compliance needs
- Monitor index size and performance

### 3. Security

For production:
- Change default passwords
- Enable SSL/TLS for HEC
- Use proper authentication tokens
- Implement RBAC in Splunk

### 4. Resource Management

- Monitor Splunk resource usage
- Adjust PVC sizes based on log volume
- Consider log rotation and archival policies

## Alerts and Dashboards

### Recommended Alerts

```spl
# High error rate alert
index=edge_app level=ERROR
| stats count by component
| where count > 50

# Model update failures
index=edge_app component="model_updater" level=ERROR
| stats count by detector_id
| where count > 5

# Inference latency alert
index=edge_app "processing_time_ms"
| stats avg(processing_time_ms) as avg_time by detector_id
| where avg_time > 5000
```

### Dashboard Components

1. **System Health Dashboard**
   - Container status and resource usage
   - Error rates by component
   - Request throughput

2. **Inference Analytics Dashboard**
   - Requests by detector
   - Processing times
   - Escalation rates

3. **Operational Dashboard**
   - Model update status
   - Queue depths
   - System performance metrics

## Performance Considerations

- HEC can handle thousands of events per second
- Use appropriate batch sizes for high volume
- Monitor Splunk resource consumption
- Consider data lifecycle management

## Roadmap

### Phase 1 (Current)
- ✅ Basic logging integration
- ✅ HEC event publishing
- ✅ Kubernetes deployment

### Phase 2 (Planned)
- [ ] Custom dashboards
- [ ] Automated alerts
- [ ] Performance optimization

### Phase 3 (Future)
- [ ] ML-based anomaly detection
- [ ] Predictive analytics
- [ ] Custom Splunk apps

## Support

For issues or questions:
1. Check pod logs: `kubectl logs -n edge deployment/edge-endpoint`
2. Check Splunk logs: `kubectl logs -n edge deployment/splunk`
3. Review this documentation
4. Check Splunk docs: https://docs.splunk.com

