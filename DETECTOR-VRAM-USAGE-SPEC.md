# Detector VRAM Usage Tracking

## Goal

Track VRAM usage per detector on the edge device so operators can see how GPU memory is allocated
across detectors and how much capacity remains. The end-state visualization is a **pie chart** on
the status page: one slice per detector, one slice for free VRAM, and (if applicable) an "Other"
slice for GPU memory in use but not attributable to any detector's inference pods.

Non-edge-endpoint GPU usage (e.g., other workloads on the device) is not explicitly tracked, but
shows up in the "Other" slice.

## Background

Each detector on the edge can have up to two inference pods:
- **Primary** (`inferencemodel-primary-{detector_id}`) -- runs the main detection model.
- **OODD** (`inferencemodel-oodd-{detector_id}`) -- runs the out-of-distribution detection model.

Both pods share the same GPU(s) and consume VRAM. The inference server is a custom FastAPI app
(in the `zuuul` repo) running PyTorch. Each pod is assigned a single GPU via `CUDA_VISIBLE_DEVICES`.

Today, the edge endpoint status page reports no GPU or VRAM metrics.

## Why VRAM (not GPU compute utilization)?

VRAM usage is a **capacity planning** metric: "Can I fit another detector on this GPU?"
GPU compute utilization is a **throughput** metric: "How busy are the GPU cores right now?"

VRAM is the right choice here because:
- It is essentially static once models are loaded (confirmed by load testing).
- It directly answers the operator question: "Do I have room for more detectors?"
- GPU compute utilization is better suited for load testing / monitoring dashboards.

## Design

### VRAM collection approaches

There are two possible approaches for collecting per-pod VRAM. We implement Approach A now as a
proof of concept. Approach B is documented as the recommended long-term solution.

#### Approach A: k8s exec (implemented)

The status monitor uses the Kubernetes exec API to run a single shell script inside each
inference pod. No changes to the inference server (zuuul repo) are required.

PID namespace isolation on modern kernels prevents containers from seeing their own host PIDs,
so direct PID-to-container mapping is not possible. Instead, the status monitor:

1. Execs nvidia-smi in a **single** inference pod to get GPU totals and the global per-process
   VRAM list. (nvidia-smi sees all host processes regardless of PID namespace.)
2. Lists inference pods from the Kubernetes API, sorted by creation timestamp.
3. Sorts nvidia-smi GPU processes by PID (ascending).
4. Maps processes to pods by position: the first process (lowest PID) maps to the first pod
   (earliest creation time), and so on. This works because PIDs are assigned monotonically
   and pod creation order is deterministic.

If there are more nvidia-smi processes than inference pods, the extras are unattributed and
show up as "Other" in the frontend.

**Pros:** No zuuul changes, works with existing inference images, only one exec call needed.
**Cons:** PID-to-pod mapping is heuristic (relies on PID ordering matching pod creation order).
Could be inaccurate if non-inference GPU processes have PIDs interleaved with inference ones.

#### Approach B: Inference server `/vram` endpoint (future)

Add a `GET /vram` endpoint to the inference server in zuuul. Each pod reports its own VRAM usage
directly. The status monitor calls `http://{pod_ip}:8000/vram` for each inference pod.

**Pros:** Clean API, fast, no PID namespace complexity, testable in isolation.
**Cons:** Requires a zuuul change and new inference image deployment.

When Approach B is implemented, the status monitor should prefer it (call `/vram` first) and
fall back to Approach A for pods running older images.

### New endpoint: `GET /status/vram.json` (edge-endpoint repo)

Lives in `status_web.py` alongside the existing metrics endpoint. Collects VRAM by:
1. Listing inference pods via the Kubernetes API (using `groundlight.dev/detector-id` and
   `groundlight.dev/model-name` annotations).
2. For each running pod, collecting VRAM via k8s exec (Approach A).
3. Aggregating results per detector (summing primary + OODD pod VRAM).
4. Grouping GPU totals by `gpu_uuid` for multi-GPU support.

Results are cached with a 30-second TTL since VRAM is static once models are loaded.

Response:
```json
{
    "gpus": [
        {
            "index": 0,
            "uuid": "GPU-abc123...",
            "name": "NVIDIA GeForce RTX 3080",
            "total_bytes": 8589934592,
            "used_bytes": 6442450944,
            "free_bytes": 2147483648
        }
    ],
    "detectors": [
        {
            "detector_id": "det_abc123",
            "primary_vram_bytes": 1073741824,
            "oodd_vram_bytes": 536870912,
            "total_vram_bytes": 1610612736
        }
    ]
}
```

Detector names are not included in this response; the frontend looks them up from the existing
`/status/metrics.json` detector_details data.

### Rolling updates

During a Kubernetes rolling update, a detector can temporarily have duplicate pods (e.g., two
primary pods while the new one starts and the old one terminates). The aggregation logic **sums**
VRAM for all running pods of the same type (primary or OODD) per detector, so the chart
accurately reflects the temporary VRAM spike during rollouts.

### Status page changes

Add a "VRAM Usage" section to the status page with a **donut pie chart** per GPU showing:
- One colored slice per detector (primary + OODD combined).
- An "Other" slice if GPU used memory exceeds the sum of detector pod VRAM.
- A gray "Free" slice for remaining GPU capacity.
- A legend mapping colors to detector names with byte values.

### Cloud reporting

VRAM usage data is **not** sent to OpenSearch for now.

### Multi-GPU support

The schema supports multiple GPUs. Each inference pod reports which GPU it is on (`gpu_uuid`).
The status page renders one chart per GPU.

**Known limitation (Approach A):** The current aggregation does not group detectors by GPU.
On a multi-GPU system, all detectors appear under every GPU chart. This is acceptable for the
initial proof of concept (the target device has a single GPU) and should be fixed when either
Approach B is implemented or multi-GPU devices are actively used.

### Graceful degradation

- If a pod does not have `nvidia-smi` available (CPU inference), it is skipped.
- If the device has no GPU (CPU inference flavor), the VRAM section shows "No GPU data available."
- If no inference pods are running, the section shows an empty state.
- If a pod's processes have no VRAM allocated (model not yet loaded), it is excluded from the
  detector breakdown.
