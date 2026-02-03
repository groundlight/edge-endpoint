# Edge Metrics

This module tracks image query activity metrics for each detector and reports them to the cloud.

## Tracked Metrics

| Metric | Description |
|--------|-------------|
| `iqs` | Total image queries submitted |
| `escalations` | Queries sent to the cloud for processing (below confidence threshold, but may be rate limited) |
| `audits` | Confident edge predictions sampled for quality auditing |
| `below_threshold_iqs` | Queries where edge confidence was below the threshold (includes both escalated and rate-limited) |

## Reported Fields

For each detector, the following fields are reported hourly:

- `hourly_total_<metric>` - count for the previous hour
- `last_<metric>` - timestamp of the most recent occurrence (singular form, e.g., `last_iq`)

## Filesystem Storage

Metrics are stored in `/opt/groundlight/device/edge-metrics/detectors/<detector_id>/`:

```
last_iqs                              # timestamp file
last_escalations
last_audits
last_below_threshold_iqs
iqs_<pid>_YYYY-MM-DD_HH               # hourly counter files (per process)
escalations_<pid>_YYYY-MM-DD_HH
audits_<pid>_YYYY-MM-DD_HH
below_threshold_iqs_<pid>_YYYY-MM-DD_HH
```

Hourly files older than 2 hours are automatically cleaned up.

## Key Files

- `iq_activity.py` - Records and retrieves activity metrics
- `metric_reporting.py` - Collects and sends metrics to the cloud API
