# Groundlight Edge Endpoint

(For instructions on running on Balena, see [here](./deploy/balena-k3s/README.md))

Run your Groundlight models on-prem by hosting an Edge Endpoint on your own hardware.  The Edge Endpoint exposes the exact same API as the Groundlight cloud service, so any Groundlight application can point to the Edge Endpoint simply by configuring the `GROUNDLIGHT_ENDPOINT` environment variable as follows:

```bash
export GROUNDLIGHT_ENDPOINT=http://localhost:30101
# This assumes your Groundlight SDK application is running on the same host as the Edge Endpoint.
```

The Edge Endpoint will attempt to answer image queries using local models for your detectors.  If it can do so confidently, you get faster and cheaper responses. If it can't, it will escalate the image queries to the cloud for further analysis.

## Running the Edge Endpoint

To set up the Edge Endpoint, please refer to the [deploy README](deploy/README.md).

### Configuring detectors for the Edge Endpoint

While not required, configuring detectors provides fine-grained control over the behavior of specific detectors on the edge. Please refer to [the guide to configuring detectors](/CONFIGURING-DETECTORS.md) for more information.

### Using the Edge Endpoint with your Groundlight application.

Any application written with the [Groundlight SDK](https://pypi.org/project/groundlight/) can work with an Edge Endpoint without any code changes.  Simply set an environment variable with the URL of your Edge Endpoint like:

```bash
export GROUNDLIGHT_ENDPOINT=http://localhost:30101
```

To find the correct port, run `kubectl get services` and you should see an entry like this:
```
NAME                                                        TYPE       CLUSTER-IP      EXTERNAL-IP   PORT(S)                         AGE
service/edge-endpoint-service                               NodePort   10.43.141.253   <none>        30101:30101/TCP                 23m
```

The port is the second number listed under ports for the `edge-endpoint-service` (in this case, 30101).

If you'd like more control, you can also initialize the `Groundlight` SDK object with the endpoint explicitly like this:

```python
from groundlight import Groundlight

gl = Groundlight(endpoint="http://localhost:30101")

det = gl.get_or_create_detector(name="doorway", query="Is the doorway open?")
img = "./docs/static/img/doorway.jpg"
with open(img, "rb") as img_file:
    byte_stream = img_file.read()

image_query = gl.submit_image_query(detector=det, image=byte_stream)
print(f"The answer is {image_query.result}")
```

See the [SDK's getting started guide](https://code.groundlight.ai/python-sdk/docs/getting-started) for more info about using the Groundlight SDK.

## Development and Internal Architecture

This section describes the various components that comprise the Groundlight Edge Endpoint, and how they interoperate.
This might be useful for tuning operational aspects of your endpoint, contributing to the project, or debugging problems.

### Components and terms

Inside the edge-endpoint pod there are two containers: one for the edge logic and another one for creating/updating inference deployments.

* `edge-endpoint` container: This container handles the edge logic.
* `inference-model-updater` container: This container checks for changes to the models being used for edge inference and updates them when new versions are available.
* `status-monitor` container: This container serves the status page, and reports metrics to the cloud.

By default, each detector will have 2 `inferencemodel` pods, one for the primary model and one for the out of domain detection (OODD) model.
When running in minimal mode, only a single `inferencemodel` pod is used, which uses a single model to perform both primary and OODD inference. 
Each `inferencemodel` pod contains one container.

* `inference-server container`: This container holds the edge model

* `Cloud API:` This is the upstream API that we use as a fallback in case the edge logic server encounters problems. It is set to `https://api.groundlight.ai`.

* `Endpoint url:` This is the URL where the endpoint's functionality is exposed to the SDK or applications.  (i.e., the upstream you can set for the Groundlight application). This is set to `http://localhost:30101`.

## Logging and Observability

The Edge Endpoint supports multiple logging modes for different environments:

* **Standard Mode**: Basic logging to stdout/files, accessible with `k logs` (default)
* **Local Splunk Mode**: Local Splunk container + OpenTelemetry collector  
* **Cloud Splunk Mode**: External Splunk + OpenTelemetry collector (in development)

### Quick Start

```bash
# Standard logging (default)
helm upgrade -i -n default edge-endpoint edge-endpoint/groundlight-edge-endpoint \
  --set groundlightApiToken="${GROUNDLIGHT_API_TOKEN}"

# Local Splunk for testing
helm upgrade -i -n default edge-endpoint edge-endpoint/groundlight-edge-endpoint \
  --set loggingMode="local-splunk" \
  --set global.otelEnabled=true 

# External Splunk for production (coming soon)
```

## Attribution

This product includes software developed by third parties, which is subject to their respective open-source licenses.

See [THIRD_PARTY_LICENSES.md](./licenses/THIRD_PARTY_LICENSES.md) for details and license texts.