# Rollout Test
Tools that test the Edge Endpoint's ability to handle model rollouts and inference pod management.

## To Run (with `uv`)
1. Install dependencies into a virtual environment: `uv sync`
2. Set your Groundlight Edge Endpoint URL: `export GROUNDLIGHT_ENDPOINT="http://<EDGE_ENDPOINT_IP>:30101"`
3. Run the script using the environment: `uv run python generate_repeated_rollouts.py num_detectors --detector_mode BINARY`.
4. Let the script run for several minutes and monitor the rollout behavior.
