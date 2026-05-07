"""Mock backend for status page frontend development.

Serves synthetic detector/resource data based on state in /tmp/mock-state.json.
Controlled via mock_control.py or by editing the state file directly.

Usage:
    python mock_server.py          # serves on :3001
    MOCK=1 npx vite --host         # point Vite proxy at this server
"""

import json
import random
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.request import urlopen

PORT = 3001
REAL_ENDPOINT = "http://localhost:30101"
STATE_FILE = "/tmp/mock-state.json"

GB = 1024**3
DEFAULT_TOTAL_VRAM_GB = 15  # approx. Tesla T4
DEFAULT_TOTAL_RAM_GB = 15
EDGE_ENDPOINT_RAM_BYTES = 1_200_000_000  # synthetic baseline for non-inference pods
OTHER_RAM_BASELINE_BYTES = 2_800_000_000  # kernel, kubelet, unattributed ns-local pods

NAMES = [
    "Hardhat Detection",
    "Forklift Counter",
    "Spill Detection",
    "PPE Compliance",
    "Fire Extinguisher",
    "Door Open/Closed",
    "Conveyor Belt",
    "Parking Lot",
    "Safety Vest",
    "Gauge Reading",
]


def _make_detector(i: int) -> dict:
    """Synthesise a single mock detector for index `i`.

    There is no cap on detector count; the pool is generated on demand by
    cycling through NAMES and appending an integer suffix on each cycle
    (e.g. "Hardhat Detection", ..., "Hardhat Detection 1", ...). Resource
    values are seeded per-index so the same `i` always produces the same
    detector across calls.
    """
    cycle = i // len(NAMES)
    base_name = NAMES[i % len(NAMES)]
    name = base_name if cycle == 0 else f"{base_name} {cycle}"
    rng = random.Random(i)
    return {
        "id": f"det_{i:04d}_{base_name.replace(' ', '_')[:12]}",
        "name": name,
        "primary_vram": rng.randint(380, 430) * 1_000_000,
        "oodd_vram": rng.randint(380, 400) * 1_000_000,
        "primary_ram": rng.randint(780, 1250) * 1_000_000,
        "oodd_ram": rng.randint(780, 850) * 1_000_000,
    }


DEFAULT_STATE = {
    "num_detectors": 3,
    "loading": False,
    "eviction": 75,
    "synthetic": True,
    "total_vram_gb": DEFAULT_TOTAL_VRAM_GB,
    "total_ram_gb": DEFAULT_TOTAL_RAM_GB,
}


def read_state():
    """Loads mock state from disk, falling back to defaults on any error."""
    try:
        with open(STATE_FILE) as f:
            raw = json.load(f)
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        raw = {}
    return {
        "num_detectors": max(0, int(raw.get("num_detectors", DEFAULT_STATE["num_detectors"]))),
        "loading": bool(raw.get("loading", DEFAULT_STATE["loading"])),
        "eviction": int(raw.get("eviction", DEFAULT_STATE["eviction"])),
        "synthetic": bool(raw.get("synthetic", DEFAULT_STATE["synthetic"])),
        "total_vram_gb": max(1, int(raw.get("total_vram_gb", DEFAULT_STATE["total_vram_gb"]))),
        "total_ram_gb": max(1, int(raw.get("total_ram_gb", DEFAULT_STATE["total_ram_gb"]))),
    }


def build_resources(state):
    """Builds a synthetic /status/resources.json payload from the mock state."""
    num_detectors = state["num_detectors"]
    loading = state["loading"]
    total_vram = state["total_vram_gb"] * GB
    total_ram = state["total_ram_gb"] * GB

    detectors = []
    used_vram = 200_000_000 if num_detectors > 0 else 0
    used_ram = EDGE_ENDPOINT_RAM_BYTES + OTHER_RAM_BASELINE_BYTES
    loading_vram = 0
    loading_ram = 0
    loading_gpu_compute = 0.0
    loading_gpu_memory = 0.0

    for i in range(num_detectors):
        d = _make_detector(i)
        det_vram = d["primary_vram"] + d["oodd_vram"]
        det_ram = d["primary_ram"] + d["oodd_ram"]
        primary_gpu_compute = 8.0 + i * 3.0
        oodd_gpu_compute = 3.0 + i
        primary_gpu_memory = 5.0 + i * 2.0
        oodd_gpu_memory = 2.0 + i
        detectors.append(
            {
                "detector_id": d["id"],
                "cpu_utilization_pct": {
                    "primary": 1.0 + i,
                    "oodd": 0.5 + i,
                    "total": 1.5 + i * 2,
                },
                "ram_bytes": {
                    "primary": d["primary_ram"],
                    "oodd": d["oodd_ram"],
                    "total": det_ram,
                },
                "gpu": {
                    "vram_bytes": {
                        "primary": d["primary_vram"],
                        "oodd": d["oodd_vram"],
                        "total": det_vram,
                    },
                    "compute_utilization_pct": {
                        "primary": primary_gpu_compute,
                        "oodd": oodd_gpu_compute,
                        "total": min(primary_gpu_compute + oodd_gpu_compute, 100.0),
                    },
                    "memory_bandwidth_pct": {
                        "primary": primary_gpu_memory,
                        "oodd": oodd_gpu_memory,
                        "total": min(primary_gpu_memory + oodd_gpu_memory, 100.0),
                    },
                },
            }
        )
        used_vram += det_vram
        used_ram += det_ram

    if loading:
        loading_vram = 800_000_000
        loading_ram = 1_600_000_000
        loading_gpu_compute = 12.0
        loading_gpu_memory = 8.0
        used_vram += loading_vram
        used_ram += loading_ram

    has_gpu = num_detectors > 0 or loading
    vram_total_bytes = total_vram if has_gpu else 0
    vram_used_bytes = min(used_vram, total_vram) if has_gpu else 0
    detector_ram = sum(d["ram_bytes"]["total"] for d in detectors)
    detector_vram = sum(d["gpu"]["vram_bytes"]["total"] for d in detectors)
    detector_cpu = sum(d["cpu_utilization_pct"]["total"] for d in detectors)
    detector_gpu_compute = sum(d["gpu"]["compute_utilization_pct"]["total"] for d in detectors)
    detector_gpu_memory = sum(d["gpu"]["memory_bandwidth_pct"]["total"] for d in detectors)
    gpu_compute = min(detector_gpu_compute + loading_gpu_compute, 100.0) if has_gpu else 0.0
    gpu_memory = min(detector_gpu_memory + loading_gpu_memory, 100.0) if has_gpu else 0.0
    loading_cpu = 2.0 if loading else 0.0
    edge_endpoint_cpu = 5.0
    other_cpu = max(0.0, 10.0 + num_detectors * 6.0 + (8.0 if loading else 0.0) - detector_cpu)
    total_cpu = min(detector_cpu + loading_cpu + edge_endpoint_cpu + other_cpu, 100.0)
    return {
        "system": {
            "cpu_utilization_pct": {
                "total": total_cpu,
                "detectors": detector_cpu,
                "loading_detectors": loading_cpu,
                "edge_endpoint": edge_endpoint_cpu,
                "other": other_cpu,
            },
            "ram_bytes": {
                "total": total_ram,
                "used": min(used_ram, total_ram),
                "detectors": detector_ram,
                "loading_detectors": loading_ram,
                "edge_endpoint": EDGE_ENDPOINT_RAM_BYTES,
                "other": OTHER_RAM_BASELINE_BYTES,
                "eviction_threshold_pct": state["eviction"],
            },
            "gpu": {
                "vram_bytes": {
                    "total": vram_total_bytes,
                    "used": vram_used_bytes,
                    "detectors": detector_vram,
                    "loading_detectors": loading_vram,
                    "edge_endpoint": 0,
                    "other": max(0, vram_used_bytes - detector_vram - loading_vram),
                },
                "compute_utilization_pct": {
                    "total": gpu_compute,
                    "detectors": detector_gpu_compute,
                    "loading_detectors": loading_gpu_compute,
                    # Only inference pods are expected to consume GPU compute in the mock edge namespace.
                    "edge_endpoint": 0.0,
                    "other": 0.0,
                },
                "memory_bandwidth_pct": {
                    "total": gpu_memory,
                    "detectors": detector_gpu_memory,
                    "loading_detectors": loading_gpu_memory,
                    # Only inference pods are expected to consume GPU memory bandwidth in the mock edge namespace.
                    "edge_endpoint": 0.0,
                    "other": 0.0,
                },
                "devices": (
                    [
                        {
                            "index": 0,
                            "uuid": "GPU-mock-0",
                            "name": "Mock GPU",
                            "vram_bytes": {
                                "total": vram_total_bytes,
                                "used": vram_used_bytes,
                                "free": max(vram_total_bytes - vram_used_bytes, 0),
                            },
                            "compute_utilization_pct": gpu_compute,
                            "memory_bandwidth_pct": gpu_memory,
                        }
                    ]
                    if has_gpu
                    else []
                ),
            },
        },
        "detectors": detectors,
    }


_PIPELINE_CONFIG_BASIC = "generic-cached-timm\ncalibrated-mlp"

# Realistic-looking multi-stage pipeline used to exercise YAML syntax
# highlighting in the Pipeline column. Stages have nested keys, strings,
# numbers, and booleans so every token type renders.
_PIPELINE_CONFIG_RICH = """\
stages:
  - name: preprocess
    type: image-resize
    params:
      target_height: 224
      target_width: 224
      interpolation: bilinear
  - name: backbone
    type: generic-cached-timm
    params:
      model: tf_efficientnet_b0
      pretrained: true
      cache_features: true
  - name: head
    type: calibrated-mlp
    params:
      hidden_dim: 256
      dropout: 0.1
      temperature: 1.4
"""


def build_metrics(state):
    detector_details = {}
    for i in range(state["num_detectors"]):
        d = _make_detector(i)
        # Give the first detector a richer multi-stage pipeline so the
        # Pipeline column actually exercises YAML syntax highlighting in dev.
        pipeline_config = _PIPELINE_CONFIG_RICH if i == 0 else _PIPELINE_CONFIG_BASIC
        detector_details[d["id"]] = {
            "detector_name": d["name"],
            "status": "ready",
            "query": f"Is the {d['name'].lower()} visible?",
            "mode": "BINARY",
            "deploy_time": f"2026-04-10T10:{i:02d}:00Z",
            "last_updated_time": "2026-04-10T19:30:00Z",
            "pipeline_config": pipeline_config,
            "edge_inference_config": {"enabled": True, "always_return_edge_prediction": True},
        }
    return {
        "device_info": {"hostname": "mock-device", "ip": "10.0.0.1"},
        "activity_metrics": {
            "activity_hour": "2026-04-29_19",
            "num_detectors_lifetime": state["num_detectors"],
            "num_detectors_active_1h": state["num_detectors"],
            "confidence_histogram": {
                "version": 2,
                "bucket_width": 5,
                "counts": [61, 0, 0, 0, 0, 0, 0, 1, 0, 0, 2, 0, 9, 48, 269, 131, 4],
            },
            "detector_activity_previous_hour": json.dumps(
                {
                    _make_detector(i)["id"]: {
                        "hourly_total_iqs": 240 - 30 * i,
                        "below_threshold_iqs": {"YES": 4, "NO": 1},
                        "escalations": {"YES": 1},
                    }
                    for i in range(min(state["num_detectors"], 3))
                }
            ),
        },
        "failed_escalations": {},
        "detector_details": json.dumps(detector_details),
        "k3s_stats": {
            # Mirror production: get_deployments() in system_metrics.py uses
            # str(list) (Python repr with single quotes), not json.dumps. The
            # frontend rehydrate path leaves it as a string since it's not
            # valid JSON.
            "deployments": str(["edge/edge-endpoint", "edge/edge-endpoint-network-healer"]),
            "pod_statuses": json.dumps(
                {
                    "edge-endpoint-5755bcc876-2z6cq": "Running",
                    "edge-endpoint-network-healer-5c9f996f4f-zzlk5": "Running",
                    "create-ecr-creds-f9jhn": "Failed",
                }
            ),
            "container_images": json.dumps(
                {
                    "edge-endpoint-5755bcc876-2z6cq": {
                        "edge-endpoint": "ecr.amazonaws.com/edge-endpoint:dev@sha256:abc123",
                        "nginx": "docker.io/library/nginx@sha256:def456",
                    },
                }
            ),
        },
    }


def build_edge_config(state):
    """Build a synthetic /edge-config payload mirroring EdgeConfigManager.active().to_payload()."""
    detectors = []
    for i in range(state["num_detectors"]):
        d = _make_detector(i)
        detectors.append({"detector_id": d["id"], "edge_inference_config": "default"})
    return {
        "global_config": {
            "confident_audit_rate": 0.01,
            "refresh_rate": 60,
        },
        "edge_inference_configs": {
            "default": {
                "enabled": True,
                "always_return_edge_prediction": True,
                "min_time_between_escalations": 2.0,
            },
        },
        "detectors": detectors,
    }


class MockHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        state = read_state()

        if state.get("synthetic", True):
            if self.path == "/status/resources.json":
                data = build_resources(state)
            elif self.path == "/status/metrics.json":
                data = build_metrics(state)
            elif self.path == "/edge-config":
                data = build_edge_config(state)
            else:
                self.send_error(404)
                return
            body = json.dumps(data).encode()
        else:
            try:
                resp = urlopen(f"{REAL_ENDPOINT}{self.path}", timeout=5)
                body = resp.read()
            except Exception as e:
                self.send_error(502, f"Failed to reach real endpoint: {e}")
                return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        state = read_state()
        mode = "synthetic" if state.get("synthetic", True) else "real"
        print(f"[{mode}] {self.path}")


if __name__ == "__main__":
    print(f"Mock server on :{PORT}, reading state from {STATE_FILE}")
    HTTPServer(("", PORT), MockHandler).serve_forever()
