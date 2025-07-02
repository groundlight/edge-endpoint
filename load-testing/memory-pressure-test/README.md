# Memory Pressure Test
Tools that test the Edge Endpoint's resilience under memory pressure by spawning multiple inference pods simultaneously.

## To Run (with `uv`)
1. Install dependencies into a virtual environment: `uv sync`
1. Set your Groundlight Edge Endpoint URL: `export GROUNDLIGHT_ENDPOINT="http://<EDGE_ENDPOINT_IP>:30101"`
1. Run the script using the environment: `uv run python memory_pressure_test.py num_detectors detector_mode`.
1. Let the script run for several minutes and then check if the Edge Endpoint is still responsive.