# Load Testing the Edge Endpoint

This directory contains scripts to comprehensively test an edge endpoint's performance, infrastructure resilience, and deployment capabilities. These include concurrent client load testing, memory pressure testing with multiple inference pods, and model rollout validation. The tools here are actively under development and may be changed at any time. 

## Multiple Client Throughput Test

Tests the Edge Endpoint's ability to handle concurrent client load by spawning multiple client processes that ramp up gradually from 1 to N workers, measuring throughput, latency, and response times over time.

### Setting up an edge endpoint

An edge endpoint should be set up on the machine you want to do load testing for. Follow the steps in the [main README](/README.md). Additionally, you'll want to make the following modifications:
* When load testing, queries should always be answered by the edge model and never escalated to the cloud. To achieve this, in `edge_config.yaml` your detector that you'll be submitting images to should have the `no_cloud` edge inference config:
```
detectors:
  - detector_id: "det_xyz"
    edge_inference_config: "no_cloud"
```

* You'll want to configure both the edge endpoint and the inference server to have the optimal number of workers. A general guideline is that your number of edge endpoint workers shouldn't exceed the number of CPU cores on your machine. Try to set your number of inference workers to maximize GPU utilization (if using a GPU).

    * **To configure edge endpoint workers**: Edit the `--workers` parameter in [launch-edge-logic-server.sh](/app/bin/launch-edge-logic-server.sh). Change from the default:
    ```bash
    poetry run uvicorn \
        --workers 8 \  # You can tweak this for load testing
        --host 0.0.0.0 \
        --port ${APP_PORT} \
        --proxy-headers \
        app.main:app
    ```

    * **To configure inference server workers**: Set the `WORKERS` environment variable in the inference deployment template at [inference-deployment-template.yaml](/deploy/helm/groundlight-edge-endpoint/files/inference-deployment-template.yaml). Change the value from `"1"` to your desired number of workers:
    ```yaml
    - name: WORKERS  # Number of uvicorn workers for the inference server
      value: "4"  # Increase this number for load testing
    ```

Some trial and error will likely be necessary to figure out the ideal configuration.

After setting these config options, you should run/re-run the upgrade command to deploy with your new configuration. 

#### If using setup-ee.sh: 

Run/re-run the [setup edge endpoint script](/deploy/bin/setup-ee.sh).

#### If using helm:

Reinstall the endpoint and set the configFile to the `edge-config.yaml` that you just modified:

```
# For an endpoint with default values:
helm upgrade -i -n default edge-endpoint edge-endpoint/groundlight-edge-endpoint \
  --set groundlightApiToken="${GROUNDLIGHT_API_TOKEN}" --set-file configFile=/path/to/your/edge-config.yaml
```


### Configuring the load testing scripts

Most configuration of the load testing scripts is done in [config.py](./config.py).
* `ENDPOINT_URL` is the url of the edge endpoint that you've set up. This will follow the format `http://<ip of host machine>:<exposed edge-endpoint-service port>`. 
* `DETECTOR_IDS` is a list of the detector ids that you'll be submitting images to.
* `NUM_OBJECTS_EXPECTED` is the number of objects expected to be detected in each image. If using a binary detector, this should be `None`. If this is set to a number, the load testing script will check that the number of objects detected in each image matches this value. If it doesn't, the client process will print an error message. This is useful for making sure that the object detection model is working as expected.
* `IMAGE_PATH` is the path to the image that the client processes will submit to the endpoint as part of load testing. Image size may affect processing times. By default, this points to `dog_resized_256x256.jpeg`.
* `LOG_FILE` is the path to the file where logs from the client processes will be written and read from. If it doesn't exist, the file will be created. Each time the load test script runs, it will overwrite the contents of the file.
* `TIME_BETWEEN_RAMP` is the amount of seconds the load testing script will wait before each subsequent ramp step. 
* `REQUESTS_PER_SECOND` is the rate of requests that each client process will attempt to send. 

### Running the load testing scripts.

It's recommended to generate the load from a separate machine than the one hosting the endpoint to ensure maximum resources are available for the endpoint to use.

Before running the script, ensure you have set the `GROUNDLIGHT_API_TOKEN` environment variable. The api token should belong to an account with access to the detectors you will be sending image queries to.

The usage of `multiple_client_throughput_test.py` is:
```
uv run python multiple_client_throughput_test.py [options]
```

#### Options
* `--max-clients` (optional, default: 10)
    * Specifies the maximum number of processes (clients) to ramp up to during the test.
* `--step-size` (optional, default: 1)
    * Sets the number of clients to add at each step in ramp-up mode. This will also be the starting number of clients.
* `--use-preset-schedule` (optional)
    * Enables using a preset schedule, which will ignore step-size and max-clients values and instead follow a custom ramping logic defined in the script. 
    * This mode will ramp from 1 to 60 clients, with smaller steps at the beginning and larger steps towards the end.

After the load test finishes, it will automatically parse the results and generate graphs. If you want to rerun this step, you can also manually run `parse_load_test_logs.py`:
```
uv run python parse_load_test_logs.py
```

If you want to monitor CPU and GPU utilization on the host machine during the load test, you can run `monitor_cpu_gpu_usage.py`: 
```
uv run python monitor_cpu_gpu_usage.py <duration>
```

#### Positional Arguments
* `<duration>` (required)
    * Specifies the number of seconds to monitor the system utilization for. 

To monitor system utilization during the load test, you'll want to separately run the monitoring script on the host machine before beginning the load testing. The duration should be set to the duration of the load test (which is determined by `TIME_BETWEEN_RAMP * <number of steps>` and printed to the console right after running `multiple_client_throughput_test.py`). 

Once the scripts have finished running, you can review the generated plots to assess the results.


## Memory Pressure Test

Tests the Edge Endpoint's resilience under memory pressure by spawning multiple inference pods simultaneously.

### Setup for Memory Pressure Test
1. Set your Groundlight Edge Endpoint URL: `export GROUNDLIGHT_ENDPOINT="http://<EDGE-ENDPOINT-IP>:30101"`
1. Set your Groundlight API Token: `export GROUNDLIGHT_API_TOKEN=<YOUR-GROUNDLIGHT-API-TOKEN>`


### Run
1. Uninstall the Edge Endpoint with `helm uninstall -n default edge-endpoint` (for repeatable results, it's usually best to start from zero).
1. Run the script: `uv run python memory_pressure_test.py NUM_DETECTORS DETECTOR_MODE`. Currently the script supports `BINARY` and `COUNT` modes.
1. Observe that the script prints errors like `Failed to connect to Groundlight`. This is normal because you haven't installed it yet.
1. Helm install the Edge Endpoint according to the instructions in the [deploy README](../../deploy/README.md). Once the endpoint comes online, the script will be able to communicate with it, and the test's timer will start.
1. The script will run until all detectors receive an edge answer in a single iteration, which means that all requested inference pods have come online. The script will report the amount of time it took for all pods to come online. 

### Configure
You can experiment with different edge configurations in `configs/edge-config.yaml`. Generally, it's worthwhile to at least test the following configurations:
1. No configurations: let the Edge Endpoint spawn inference pods as they are requested.
1. Edge Answers with escalation: add the following configuration for each of your detectors. 
    ```
    detectors:
        - detector_id: "det_xxxxxx"
            edge_inference_config: "edge_answers_with_escalation"
    ```
### Evaluate
Below are some commands that are commonly run to evaluate the performance of the Edge Endpoint during this load test. 
1. CPU memory utilization: `htop`.
1. GPU VRAM utilization: `nvtop`. Check that GPU VRAM utilization is evenly spread across all available GPUs. 
1. Inference pod status: `watch kubectl get pods -n edge`. Check that all pods are online and that no restarts occurred.


## Repeated Rollouts Test

A test that validates the Edge Endpoint's ability to handle model rollouts by periodically submitting labels to multiple detectors to trigger model training in the cloud, and in turn, model download on the edge.

If the Edge Endpoint is successful, it will be able to download an edge model and return an edge answer for each detector.

This test is very similar to "Memory Pressure Test". It was created at a differet time to solve a different problem, but we could consider merging these tests.

### Setup
1. Set your Groundlight Edge Endpoint URL: `export GROUNDLIGHT_ENDPOINT="http://<EDGE_ENDPOINT_IP>:30101"`
1. Do a fresh helm install of your Edge Endpoint (for the script to function correctly, it needs to start with no inference pods rolled out)
1. Optionally, you can edit `global_config/refresh_rate` in `configs/edge-config.yaml` to be lower than the default, something like 20. This makes the test more difficult for the Edge Endpoint, and quicker for you to test, so it's an all-around good idea to do this.

### Run
1. Run the script: `uv run python generate_repeated_rollouts.py 3`
1. In another window, run `watch kubectl get pods -n edge` to monitor the rollouts.
1. In another window, run `kubectl logs -f -n edge -c inference-model-updater edge-endpoint-xxxxxx` to watch the `inference-model-updater` logs.

### Evaluate
1. Within a reasonable amount of time, the script should report that all detectors have received edge answers. For 3 binary detectors, expect ~200-300 seconds.
1. Inference pods should be updated in a single threaded fashion, one detector at a time.
