# Load Testing the Edge Endpoint

This directory contains scripts to 'load test' an edge endpoint, i.e., simulate a number of processes submitting requests to the endpoint and measure the throughput. The tools here are actively under development and may be changed at any time. 

## How to run a load test

### Setting up an edge endpoint

An edge endpoint should be set up on the machine you want to do load testing for. Follow the steps in the [main README](/README.md). Additionally, you'll want to make the following modifications:
* When load testing, queries should always be answered by the edge model and never escalated to the cloud. To achieve this, in `edge_config.yaml` your detector that you'll be submitting images to should have the `no_cloud` edge inference config:
```
detectors:
  - detector_id: "det_xyz"
    edge_inference_config: "no_cloud"
```

* You'll want to configure the edge-endpoint proxy and the inference server to have the optimal number of workers. A general guideline is that your number of edge-endpoint proxy workers shouldn't exceed the number of CPU cores on your machine. Try to set your number of inference workers to maximize GPU utilization (if using a GPU).
    * To increase the number of edge-endpoint proxy workers, change the `--workers` param in the CMD line of the [Dockerfile](/Dockerfile). 
    * To increase the number of inference server workers, in the [inference_deployment_template](/deploy/k3s/inference_deployment/inference_deployment_template.yaml) locate the below command and change the argument for `--workers`.
```
command:
    [
        "poetry", "run", "python3", "-m", "uvicorn", "serving.edge_inference_server.fastapi_server:app",
        "--host", "0.0.0.0",
        "--port", "8000",
        "--workers", "1"
    ]
```

Some trial and error will likely be necessary to figure out the ideal configuration.

After setting these config options, you should run/re-run the [setup edge endpoint script](/deploy/bin/setup-ee.sh) to deploy with your new configuration. You can monitor the inference pod's logs to see when all of the workers have finished starting up (if the number of workers is high, this will likely be after the pod reports being ready). 

### Configuring the load testing scripts

Most configuration of the load testing scripts is done in [config.py](./config.py).
* `ENDPOINT_URL` is the url of the edge endpoint that you've set up. This will follow the format `http://<ip of host machine>:<exposed edge-endpoint-service port>`. 
* `DETECTOR_IDS` is a list of the detector ids that you'll be submitting images to.
* `NUM_OBJECTS_EXPECTED` is the number of objects expected to be detected in each image. If using a binary detector, this should be `None`. If this is set to a number, the load testing script will check that the number of objects detected in each image matches this value. If it doesn't, the client process will print an error message. This is useful for making sure that the object detection model is working as expected.
* `IMAGE_PATH` is the path to the image that the client processes will submit to the endpoint as part of load testing. Image size may affect processing times. By default, this points to `dog_resized_256x256.jpeg`.
* `LOG_FILE` is the path to the file where logs from the client processes will be written and read from. If it doesn't exist, the file will be created. Each time the load test script runs, it will overwrite the contents of the file.
* `TIME_BETWEEN_RAMP` is the amount of seconds the load testing script will wait before each subsequent ramp step. 
* `REQUESTS-PER-SECOND` is the rate of requests that each client process will attempt to send. 

### Running the load testing scripts.

It's recommended to generate the load from a separate machine than the one hosting the endpoint to ensure maximum resources are available for the endpoint to use.

Before running the script, ensure you have set the `GROUNDLIGHT_API_TOKEN` environment variable. The api token should belong to an account with access to the detectors you will be sending image queries to.

The usage of `load_test.py` is:
```
poetry run python load_test.py [options]
```

#### Options
* `--max-clients` (optional, default: 10)
    * Specifies the maximum number of processes (clients) to ramp up to during the test.
* `--step-size` (optional, default: 1)
    * Sets the number of clients to add at each step in ramp-up mode. This will also be the starting number of clients.
* `--custom-ramp` (optional)
    * Enables custom ramping mode, which will ignore step-size and max-clients values and instead follow a custom ramping logic defined in the script. 
    * This mode will ramp from 1 to 60 clients, with smaller steps at the beginning and larger steps towards the end.

After the load test finishes, it will automatically parse the results and generate graphs. If you want to rerun this step, you can also manually run `parse_load_test_logs.py`:
```
poetry run python parse_load_test_logs.py
```

If you want to monitor CPU and GPU utilization on the host machine during the load test, you can run `monitor_cpu_gpu_usage.py`: 
```
poetry run python monitor_cpu_gpu_usage.py <duration>
```

#### Positional Arguments
* `<duration>` (required)
    * Specifies the number of seconds to monitor the system utilization for. 

To monitor system utilization during the load test, you'll want to separately run the monitoring script on the host machine before beginning the load testing. The duration should be set to the duration of the load test (which is determined by `TIME_BETWEEN_RAMP * <number of steps>` and printed to the console right after running `load_test.py`). 

Once the scripts have finished running, you can review the generated plots to assess the results.