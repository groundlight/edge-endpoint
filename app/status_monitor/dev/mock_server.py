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

random.seed(42)
DETECTOR_POOL = []
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
    "Crack Detection",
    "Weld Inspection",
    "Pallet Counter",
    "Smoke Detection",
    "Leak Detection",
    "Label Verification",
    "Package Sorting",
    "Belt Alignment",
    "Valve Position",
    "Tank Level",
    "Fence Integrity",
    "Vehicle Counter",
    "Pedestrian Safety",
    "Dock Door",
    "Aisle Clearance",
    "Bin Fullness",
    "Rust Detection",
    "Bolt Presence",
    "Cable Routing",
]
for i, name in enumerate(NAMES):
    DETECTOR_POOL.append(
        {
            "id": f"det_{i:04d}_{name.replace(' ', '_')[:12]}",
            "name": name,
            "primary_vram": random.randint(380, 430) * 1_000_000,
            "oodd_vram": random.randint(380, 400) * 1_000_000,
            "primary_ram": random.randint(780, 1250) * 1_000_000,
            "oodd_ram": random.randint(780, 850) * 1_000_000,
        }
    )


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
        "num_detectors": max(0, min(int(raw.get("num_detectors", DEFAULT_STATE["num_detectors"])), len(DETECTOR_POOL))),
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
    used_ram = 4_000_000_000
    loading_vram = 0
    loading_ram = 0

    for i in range(num_detectors):
        d = DETECTOR_POOL[i]
        det_vram = d["primary_vram"] + d["oodd_vram"]
        det_ram = d["primary_ram"] + d["oodd_ram"]
        detectors.append(
            {
                "detector_id": d["id"],
                "primary_vram_bytes": d["primary_vram"],
                "oodd_vram_bytes": d["oodd_vram"],
                "total_vram_bytes": det_vram,
                "primary_ram_bytes": d["primary_ram"],
                "oodd_ram_bytes": d["oodd_ram"],
                "total_ram_bytes": det_ram,
            }
        )
        used_vram += det_vram
        used_ram += det_ram

    if loading:
        loading_vram = 800_000_000
        loading_ram = 1_600_000_000
        used_vram += loading_vram
        used_ram += loading_ram

    has_gpu = num_detectors > 0 or loading
    return {
        "total_vram_bytes": total_vram if has_gpu else 0,
        "used_vram_bytes": min(used_vram, total_vram) if has_gpu else 0,
        "total_ram_bytes": total_ram,
        "used_ram_bytes": min(used_ram, total_ram),
        "ram_eviction_threshold_pct": state["eviction"],
        "detectors": detectors,
        "loading_vram_bytes": loading_vram,
        "loading_ram_bytes": loading_ram,
        "observed_gpus": (
            [
                {
                    "name": "Mock GPU",
                    "total_vram_bytes": total_vram,
                    "used_vram_bytes": min(used_vram, total_vram),
                    "index": 0,
                }
            ]
            if has_gpu
            else []
        ),
    }


def build_metrics(state):
    detector_details = {}
    for i in range(state["num_detectors"]):
        d = DETECTOR_POOL[i]
        detector_details[d["id"]] = {
            "detector_name": d["name"],
            "status": "ready",
            "query": f"Is the {d['name'].lower()} visible?",
            "mode": "BINARY",
            "deploy_time": f"2026-04-10T10:{i:02d}:00Z",
            "last_updated_time": "2026-04-10T19:30:00Z",
            "pipeline_config": "generic-cached-timm\ncalibrated-mlp",
            "edge_inference_config": {"enabled": True, "always_return_edge_prediction": True},
        }
    return {
        "device_info": {"hostname": "mock-device", "ip": "10.0.0.1"},
        "activity_metrics": {},
        "failed_escalations": {},
        "detector_details": json.dumps(detector_details),
        "k3s_stats": {},
    }


class MockHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        state = read_state()

        if state.get("synthetic", True):
            if self.path == "/status/resources.json":
                data = build_resources(state)
            elif self.path == "/status/metrics.json":
                data = build_metrics(state)
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
