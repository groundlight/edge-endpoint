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
If you only want to receive (high FPS) answers from the edge ml model for a detector, you can enable that by setting `always_return_edge_prediction=True` and `disable_cloud_escalation=True`. This will prevent the edge-endpoint from sending image queries to the cloud API. If you want fast edge answers regardless of confidence but still want the edge model to improve, you can set `always_return_edge_prediction=True` and `disable_cloud_escalation=False`. This mode will always return the edge ml model's answer, but it will also submit low confidence image queries to the cloud API for training so we can further improve the edge model.

To do this, edit the detector's configuration in the [edge config file](./configs/edge-config.yaml) like so:
```
detectors:
  - detector_id: 'det_xyz'
    local_inference_template: "default"
    always_return_edge_prediction: true
    disable_cloud_escalation: true

  - detector_id: 'det_ijk'
    local_inference_template: "default"
    always_return_edge_prediction: true
    min_time_between_escalations: 5

  - detector_id: 'det_abc'
    local_inference_template: "default"
```
In this example, `det_xyz` will have cloud escalation disabled because `disable_cloud_escalation` is set to `true` and `always_return_edge_prediction` is also `true`. `det_ijk` will have edge-only inference enabled because `always_return_edge_prediction` is set to `true` while `disable_cloud_escalation` is `false`. If neither `always_return_edge_prediction` nor `disable_cloud_escalation` are specified, they default to `false`, so `det_abc` will have both options disabled.

With `always_return_edge_prediction` enabled for a detector, when you make requests to it, you will receive answers from the edge model regardless of the confidence level. However, if `disable_cloud_escalation` is not set to `true`, image queries with confidences below the threshold will be escalated to the cloud and used to train the model. This configuration is useful when you want fast edge answers but still want the model to improve. In this case, the image query ID returned from the edge endpoint will correspond to the escalated query, meaning you can keep track of the ID and attempt to fetch a more confident answer from the cloud at a later point. However, note that the image query in the cloud will NOT retain the prediction made by the edge model - it will be processed in the cloud as if it were an entirely new query.

When `always_return_edge_prediction` is set to `true` and `disable_cloud_escalation` is set to `false`, the `min_time_between_escalations` field sets the minimum number of seconds that must pass between image query escalations to the cloud through background escalations. This is to prevent the edge endpoint from sending too many escalation requests in a short period of time to the cloud. The default time between escalations is 2 seconds if this config option is not set. 
This config option is not valid if `always_return_edge_prediction` is `false` or `disable_cloud_escalation` is `true`.

If `disable_cloud_escalation` is set to `true`, the edge endpoint will not send image queries to the cloud API, and you will only receive answers from the edge model. This option should be used if you don't need the model to improve and only want fast answers from the edge model. Note that no image queries submitted this way will show up in the web app or be used to train the model.

If `always_return_edge_prediction` is set to `true` for a detector and the edge inference-server for that detector is not available, attempting to send image queries to that detector will return a 503 error response.

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