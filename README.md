# Groundlight Edge Endpoint

(For instructions on running on Balena, see [here](./deploy/balena-k3s/README.md))

Run your Groundlight models on-prem by hosting an Edge Endpoint on your own hardware.  The Edge Endpoint exposes the exact same API as the Groundlight cloud service, so any Groundlight application can point to the Edge Endpoint simply by configuring the `GROUNDLIGHT_ENDPOINT` environment variable as follows:

```
GROUNDLIGHT_ENDPOINT=http://localhost:30101
# This assumes your Groundlight SDK application is running on the same host as the Edge Endpoint.
```

The Edge Endpoint will attempt to answer image queries using local models for your detectors.  If it can do so confidently, you get faster cheaper responses.  But if it can't, it will escalate the image queries to the cloud for further analysis.

## Running the Edge Endpoint

To set up the Edge Endpoint, please refer to the [deploy README](deploy/README.md). 

### Using the Edge Endpoint with your Groundlight application.

Any application written with the [Groundlight SDK](https://pypi.org/project/groundlight/) can work with an Edge Endpoint without any code changes.  Simply set an environment variable with the URL of your Edge Endpoint like:

```bash
export GROUNDLIGHT_ENDPOINT=http://localhost:30101
```

To find the correct port, run `kubectl get services` and you should see an entry like this:
```
NAME                                                        TYPE       CLUSTER-IP      EXTERNAL-IP   PORT(S)                         AGE
service/edge-endpoint-service                               NodePort   10.43.141.253   <none>        6717:30101/TCP                  23m
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

See the [SDK's getting started guide](https://code.groundlight.ai/python-sdk/docs/getting-started) for more info.

### Experimental: getting only edge model answers
If you only want to receive answers from the edge model for a detector, you can enable edge-only mode for it. This will prevent the edge endpoint from sending image queries to the cloud API. If you want fast edge answers regardless of confidence but still want the edge model to improve, you can enable edge-only inference for that detector. This mode will always return the edge model's answer, but it will also submit low confidence image queries to the cloud API for training.

To do this, edit the detector's configuration in the [edge config file](./configs/edge-config.yaml) like so:
```
detectors:
  - detector_id: 'det_xyz'
    motion_detection_template: "disabled"
    local_inference_template: "default"
    edge_only: true

  - detector_id: 'det_ijk'
    motion_detection_template: "disabled"
    local_inference_template: "default"
    edge_only_inference: true

  - detector_id: 'det_abc'
    motion_detection_template: "default"
    local_inference_template: "default"
```
In this example, `det_xyz` will have edge-only mode enabled because `edge_only` is set to `true`. `det_ijk` will have edge-only inference enabled because `edge_only_inference` is set to `true`. If `edge_only` or `edge_only_inference` are not specified, they default to false, so `det_abc` will have edge-only mode disabled. Only one of `edge_only` or `edge_only_inference` can be set to `true` for a detector.

With edge-only mode enabled for a detector, when you make requests to it, you will only receive answers from the edge model (regardless of the confidence). Additionally, note that no image queries submitted this way will show up in the web app or be used to train the model. This option should therefore only be used if you don't need the model to improve and only want fast answers from the edge model.

With edge-only inference enabled for a detector, when you make requests to it, you will only receive answers from the edge model (regardless of the confidence). However, image queries submitted this way with confidences below the threshold will be escalated to the cloud and used to train the model. This option should be used when you want fast edge answers (regardless of confidence) but still want the model to improve.

If edge-only or edge-only inference mode is enabled on a detector and the edge inference model for that detector is not available, attempting to send image queries to that detector will return a 500 error response.

This feature is currently not fully compatible with motion detection. If motion detection is enabled, some image queries may still be sent to the cloud API.

This is an experimental feature and may be modified or removed in the future.

## Development and Internal Architecture

This section describes the various components that comprise the Groundlight Edge Endpoint, and how they interoperate.
This might be useful for tuning operational aspects of your endpoint, contributing to the project, or debugging problems.

### Components and terms

Inside the edge-endpoint pod there are two containers: one for the edge logic and another one for creating/updating inference deployments. 

* `edge-endpoint container`: This container handles the edge logic.
* `inference-model-updater container`: This container checks for changes to the models being used for edge inference and updates them when new versions are available.

Each inferencemodel pod is specific to a detector. It contains one container.

* `inference-server container`: This container holds the edge model 

* `Cloud API:` This is the upstream API that we use as a fallback in case the edge logic server encounters problems. It is set to `https://api.groundlight.ai`. 

* `Edge endpoint:` This is the user-visible endpoint (i.e., the upstream you can set for the Groundlight application). This is set to `http://localhost:30101`. 