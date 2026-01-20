# Load Testing the Edge Endpoint

This directory contains scripts to comprehensively test an edge endpoint's performance, infrastructure resilience, and deployment capabilities. These include concurrent client load testing, memory pressure testing with multiple inference pods, and model rollout validation. The tools here are actively under development and may be changed at any time. 


## Setting up an Edge Endpoint
An edge endpoint should be set up on the machine where you want to perform load testing. Follow the steps in the [main README](/README.md). 

## Advanced Configuration of the Edge Endpoint
You may want to configure both the edge endpoint and the inference server containers to have the optimal number of workers. A general guideline is that your number of edge endpoint workers shouldn't exceed the number of CPU cores on your machine. Try to set your number of inference workers to maximize GPU utilization (if using a GPU).

**To configure edge endpoint workers**: Edit the `--workers` parameter in [launch-edge-logic-server.sh](/app/bin/launch-edge-logic-server.sh). Change from the default:
```bash
poetry run uvicorn \
    --workers 8 \  # You can tweak this for load testing
    --host 0.0.0.0 \
    --port ${APP_PORT} \
    --proxy-headers \
    app.main:app
```

**To configure inference server workers**: Set the `WORKERS` environment variable in the inference deployment template at [inference-deployment-template.yaml](/deploy/helm/groundlight-edge-endpoint/files/inference-deployment-template.yaml). Change the value from `"1"` to your desired number of workers:
```yaml
- name: WORKERS  # Number of uvicorn workers for the inference server
  value: "4"  # Increase this number for load testing
```

Some trial and error will likely be necessary to figure out the ideal configuration.

After setting these config options, you should run/re-run the helm upgrade command to deploy with your new configuration. 


## Running the Tests

Before running any of the test scripts, ensure you have set `GROUNDLIGHT_API_TOKEN` and `GROUNDLIGHT_ENDPOINT`, for example:
```
export GROUNDLIGHT_API_TOKEN="<YOUR-GROUNDLIGHT-API-TOKEN>"
export GROUNDLIGHT_ENDPOINT="http://<EDGE-ENDPOINT-IP>:30101"
```

### Multiple Client Throughput Test

#### Purpose
Tests the Edge Endpoint's ability to handle concurrent client load by spawning multiple client processes that ramp up gradually from 1 to N workers, measuring throughput and latency over time. During the test, host system utilization (CPU/GPU/RAM/VRAM) is also sampled and included in the generated artifacts.

#### Usage
```
uv run python multiple_client_throughput_test.py DETECTOR_MODE [options]
```

#### Options
* `DETECTOR_MODE` (required, one of: `BINARY`, `COUNT`)
* `--max-clients` (optional, default: 10)
    * Specifies the maximum number of processes (clients) to ramp up to during the test.
* `--step-size` (optional, default: 1)
    * Sets the number of clients to add at each step in ramp-up mode. This will also be the starting number of clients.
* `--time-between-ramp` (optional, default: 30)
    * Seconds to run each ramp step.
* `--requests-per-second` (optional, default: 10)
    * Per-client request rate.
* `--image-width` (optional, default: 640)
* `--image-height` (optional, default: 480)

#### Outputs
After the load test finishes, it automatically parses the results and writes a timestamped directory under `load-testing/load_tests/` containing:
* `load_test.log`: raw request + utilization events
* `load_test_results.json`: inputs, summary outputs, and run metadata
* `throughput_and_system_utilization_over_time.png`: throughput/errors/expected vs CPU/GPU/RAM/VRAM
* `time_vs_latency.png`: latency over time vs number of clients

`load-testing/load_tests/` is ignored by git by default.

#### Evaluate
Review the generated plots and `load_test_results.json`.

### Single Client FPS Test

#### Purpose
Measures end-to-end single-client throughput (frames per second) for a single detector.

#### Usage
```
uv run python single_client_fps_test.py DETECTOR_MODE [--image-width WIDTH] [--image-height HEIGHT]
```

#### Configuration
By default, this script will evaluate using the default pipeline for the given detector type. If you wish to evaluate a different pipeline, you need to:
1. Switch to the desired edge pipeline in Django admin
1. Wait until the new pipelines trains and downloads to your Edge Endpoint. You can check the status of your detector's pipeline on `http://<EDGE-ENDPOINT-IP>:30101/status`.

#### Evaluate
After the script runs, you will see a print out of the detector's performance and other relevant details of the test. 


### Memory Pressure Test

#### Purpose
Tests the Edge Endpoint's resilience under memory pressure by spawning multiple inference pods simultaneously.

#### Usage
1. Uninstall the Edge Endpoint with `helm uninstall -n default edge-endpoint` (for repeatable results, it's usually best to start from zero).
1. Run the script: `uv run python memory_pressure_test.py NUM_DETECTORS DETECTOR_MODE`. Currently the script supports `BINARY` and `COUNT` modes.
1. Observe that the script prints errors like `Failed to connect to Groundlight`. This is normal because you haven't installed it yet.
1. Helm install the Edge Endpoint according to the instructions in the [deploy README](../deploy/README.md). Once the endpoint comes online, the script will be able to communicate with it, and the test's timer will start.
1. The script will run until all detectors receive an edge answer in a single iteration, which means that all requested inference pods have come online. The script will report the amount of time it took for all pods to come online. 

#### Configuration
You can experiment with different edge configurations in `configs/edge-config.yaml`. Generally, it's worthwhile to at least test the following configurations:
1. No configurations: let the Edge Endpoint spawn inference pods as they are requested.
1. Edge Answers with escalation: add the following configuration for each of your detectors. 
    ```
    detectors:
        - detector_id: "det_xxxxxx"
            edge_inference_config: "edge_answers_with_escalation"
    ```
#### Evaluate
Below are some commands that are commonly run to evaluate the performance of the Edge Endpoint during this load test. 
1. CPU memory utilization: `htop`.
1. GPU VRAM utilization: `nvtop`. Check that GPU VRAM utilization is evenly spread across all available GPUs. 
1. Inference pod status: `watch kubectl get pods -n edge`. Check that all pods are online and that no restarts occurred.


### Repeated Rollouts Test

#### Purpose
A test that validates the Edge Endpoint's ability to handle model rollouts by periodically submitting labels to multiple detectors to trigger model training in the cloud, and in turn, model download on the edge.

If the Edge Endpoint is successful, it will be able to download an edge model and return an edge answer for each detector.

This test is very similar to "Memory Pressure Test". It was created at a differet time to solve a different problem, but we could consider merging these tests.

#### Setup
1. Set your Groundlight Edge Endpoint URL: `export GROUNDLIGHT_ENDPOINT="http://<EDGE_ENDPOINT_IP>:30101"`
1. Do a fresh helm install of your Edge Endpoint (for the script to function correctly, it needs to start with no inference pods rolled out)
1. Optionally, you can edit `global_config/refresh_rate` in `configs/edge-config.yaml` to be lower than the default, something like 20. This makes the test more difficult for the Edge Endpoint, and quicker for you to test, so it's an all-around good idea to do this.

#### Run
1. Run the script: `uv run python generate_repeated_rollouts.py 3`
1. In another window, run `watch kubectl get pods -n edge` to monitor the rollouts.
1. In another window, run `kubectl logs -f -n edge -c inference-model-updater edge-endpoint-xxxxxx` to watch the `inference-model-updater` logs.

#### Evaluate
1. Within a reasonable amount of time, the script should report that all detectors have received edge answers. For 3 binary detectors, expect ~200-300 seconds.
1. Inference pods should be updated in a single threaded fashion, one detector at a time.