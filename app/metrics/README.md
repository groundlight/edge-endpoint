# Edge Metrics

Tracks and reports metrics from edge endpoints to the cloud.

## Files

| File | Description |
|------|-------------|
| `iq_activity.py` | Records and retrieves image query activity metrics |
| `system_metrics.py` | Collects system and infrastructure metrics |
| `metric_reporting.py` | Aggregates all metrics and reports to cloud API |

## Image Query Activity Metrics

Tracked per detector in `iq_activity.py`:

| Metric | Description |
|--------|-------------|
| `iqs` | Total image queries submitted |
| `escalations` | Queries sent to the cloud for processing (includes low-confidence IQs, but also `want_async` requests, `human_review=ALWAYS` requests, and cases where edge inference is unavailable) |
| `audits` | Confident edge predictions sampled for quality auditing |
| `below_threshold_iqs` | Queries where edge confidence was below the threshold (includes both escalated iqs and iqs that were candidates for escalation but were rate-limited) |
| `confidence_histogram` | Distribution of confidence values across 5% buckets: [0-5), [5-10), ..., [95-100] |

Per-class breakdowns are tracked for `escalations`, `below_threshold_iqs`, and `confidence_histogram`, keyed by the class index from the prediction (`results["label"]`).

Reported fields per detector:
- `hourly_total_<metric>` - count for the previous hour
- `last_<metric>` - timestamp of most recent occurrence (singular form, e.g., `last_iq`)
- `escalations_by_class` - dict mapping class index to escalation count
- `below_threshold_iqs_by_class` - dict mapping class index to below-threshold count
- `confidence_histogram` - versioned envelope with aggregate and per-class data:
  ```json
  {
    "version": 2,
    "bucket_width": 5,
    "counts": [c0, c1, ..., c19],
    "by_class": {
      "0": [c0, c1, ..., c19],
      "1": [c0, c1, ..., c19]
    }
  }
  ```
  `counts[i]` is the count for bucket `[i*bucket_width, (i+1)*bucket_width)`. Version is bumped on any schema change (including bucket width changes).

### Filesystem Storage

Metrics stored in `/opt/groundlight/device/edge-metrics/detectors/<detector_id>/`:

```
last_iqs                              # timestamp files
last_escalations
last_audits
last_below_threshold_iqs
iqs_<pid>_YYYY-MM-DD_HH               # hourly counter files (per process)
escalations_<pid>_YYYY-MM-DD_HH
audits_<pid>_YYYY-MM-DD_HH
below_threshold_iqs_<pid>_YYYY-MM-DD_HH
confidence_v<version>_<bucket>_<pid>_YYYY-MM-DD_HH
confidence_v<version>_class_<index>_<bucket>_<pid>_YYYY-MM-DD_HH  # per-class counter files
escalations_v<version>_class_<index>_<pid>_YYYY-MM-DD_HH
below_threshold_iqs_v<version>_class_<index>_<pid>_YYYY-MM-DD_HH
```

Hourly files older than 2 hours are automatically cleaned up.

## System Metrics

Collected in `system_metrics.py`:

| Metric | Description |
|--------|-------------|
| `cpu_utilization` | CPU usage percentage |
| `memory_utilization` | Memory usage percentage |
| `memory_available_bytes` | Total available memory |
| `inference_flavor` | Inference runtime type |
| `deployments` | K8s deployments in namespace |
| `pod_statuses` | K8s pod phases |
| `container_images` | Container image IDs |
| `detector_details` | Per-detector config and metadata |

## Cloud Reporting

`metric_reporting.py` aggregates metrics into a payload with four sections:
- `device_info` - Device ID, CPU/memory stats, inference flavor
- `activity_metrics` - IQ activity from `iq_activity.py`
- `k3s_stats` - Kubernetes cluster info
- `detector_details` - Per-detector configuration and model info

Reports to `/v1/edge/report-metrics` endpoint.
