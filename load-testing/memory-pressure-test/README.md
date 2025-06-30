# Memory Pressure Test
Tools to test the Edge Endpoint's resilience under memory pressure by spawning multiple inference pods simultaneously.

## To Run
1. Create an environment: `python3 -m venv .venv`
1. Activate the environment: `source .venv/bin/activate`
1. Install dependencies: `pip install -r requirements.txt`
1. Set your Groundlight Edge Endpoint URL: `export GROUNDLIGHT_ENDPOINT="http://<EDGE_ENDPOINT_IP>:30101"`
1. Run the script: `python memory_pressure_test.py num_detectors detector_mode`
1. Let the script run for several minutes and then check if the Edge Endpoint is still responsive. 