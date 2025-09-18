# Rollout Test
A simple test developed to validate a fix for GL-112 (Edge Endpoint gets stuck in model download loop)

The script periodically submits labels to multiple detectors to trigger model training in the cloud, and in turn, model download on the edge.

If the Edge Endpoint is successful, it will be able to download an edge model and return an edge answer for each detector. 

## To Set Up
1. Install dependencies into a virtual environment: `uv sync`
2. Set your Groundlight Edge Endpoint URL: `export GROUNDLIGHT_ENDPOINT="http://<EDGE_ENDPOINT_IP>:30101"`
3. Do a fresh helm install of your Edge Endpoint (for the script to function correctly, it needs to start with no inference pods rolled out)
4. Optionally, you can edit `global_config/refresh_rate` in `configs/edge-config.yaml` to be lower than the default, something like 20. This makes the test more difficult for the Edge Endpoint, and quicker for you to test, so it's an all-around good idea to do this.   

## To Run
1. Run the script: `uv run python generate_repeated_rollouts.py 3`
2. In another window, run `watch kubectl get pods -n edge` to monitor the rollouts. 
3. In another window, run `kubectl logs -f -n edge -c inference-model-updater edge-endpoint-xxxxxx` to watch the `inference-model-updater` logs.

## Evaluation
1. Within a reasonable amount of time, the script should report that all detectors have received edge answers. For 3 binary detectors, expect ~200-300 seconds.
2. Inference pods should be updated in a single threaded fashion, one detector at a time.
