# Memory Pressure Test
Tools that test the Edge Endpoint's resilience under memory pressure by spawning multiple inference pods simultaneously.

## Setup
1. Install dependencies into a virtual environment: `uv sync`
1. Set your Groundlight Edge Endpoint URL: `export GROUNDLIGHT_ENDPOINT="http://<EDGE-ENDPOINT-IP>:30101"`
1. Set your Groundlight API Token: `export GROUNDLIGHT_API_TOKEN=<YOUR-GROUNDLIGHT-API-TOKEN>`

## Configure
You can experiment with different edge configurations in `configs/edge-config.yaml`. Generally, it's worthwhile to at least test the following configurations:
1. No configurations: let the Edge Endpoint spawn inference pods as they are requested.
1. Edge Answers with escalation: add the following configuration for each of your detectors. 
    ```
    detectors:
        - detector_id: "det_xxxxxx"
            edge_inference_config: "edge_answers_with_escalation"
    ```

## Run
1. Uninstall the Edge Endpoint with `helm uninstall -n default edge-endpoint` (for repeatable results, it's usually best to start from zero).
1. Run the script: `uv run python memory_pressure_test.py NUM_DETECTORS DETECTOR_MODE`. Currently the script supports `BINARY` and `COUNT` modes.
1. Observe that the script prints errors like `Failed to connect to Groundlight`. This is normal because you haven't installed it yet.
1. Helm install the Edge Endpoint according to the instructions in the [deploy README](deploy/README.md).
1. The script will run until all detectors receive an edge answer in a single iteration, which means that all requested inference pods have come online. The script will report the amount of time it took for all pods to come online. 

## Evaluate
Below are some commands that are commonly run to evaluate the performance of the Edge Endpoint during this load test. 
1. CPU memory utilization: `htop`.
1. GPU VRAM utilization: `nvtop`. Check that GPU VRAM utilization is evenly spread across all available GPUs. 
1. Inference pod status: `watch kubectl get pods -n edge`. Check that all pods are online and that no restarts occurred. 