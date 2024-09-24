# Groundlight Edge Endpoint

(For instructions on running on Balena, see [here](./deploy/balena-k3s/README.md))

Run your Groundlight models on-prem by hosting an Edge Endpoint on your own hardware.  The Edge Endpoint exposes the exact same API as the Groundlight cloud service, so any Groundlight application can point to the Edge Endpoint simply by configuring the `GROUNDLIGHT_ENDPOINT` environment variable as follows:

```
GROUNDLIGHT_ENDPOINT=http://localhost:30101
# This assumes your Groundlight SDK application is running on the same host as the Edge Endpoint.
```

The Edge Endpoint will attempt to answer image queries using local models for your detectors.  If it can do so confidently, you get faster cheaper responses.  But if it can't, it will escalate the image queries to the cloud for further analysis.

For more information on how to run Groundlight on the edge, checkout our [documentation](https://code.groundlight.ai/python-sdk/docs/building-applications/edge).

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

* `Edge endpoint:` This is the user-visible endpoint (i.e., the upstream you can set for the Groundlight application). This is set to `http://localhost:6717`. 


### Running a development edge endpoint outside a container

To develop outside docker, you need to run both the nginx proxy and the edge logic server.

The easiest way to run the nginx proxy is:

```BASH
# Install nginx (if you haven't) - for Ubuntu
sudo apt-get update && apt-get install nginx

# Make sure you `cd` into the root of this repo
sudo nginx -c $(pwd)/configs/nginx.conf
```

Then you must run the edge logic server like this:

```BASH
# Install poetry (if you haven't yet)
curl -sSL https://install.python-poetry.org | python3 -

# Install python environment
poetry install

# Run tests to confirm the system is setup properly
# (This still isn't working properly, but is getting closer.)
make test

# Run the edge logic server (http://localhost:6718)
# Note: the `--reload` option allows live code changes to be reloaded during development
poetry run uvicorn --workers 1 --host 127.0.0.1 --port 6718 app.main:app --reload
```

### See the edge API methods

Open a web browser to http://localhost/redoc. This requires that the application server is already
running either locally or in a docker container. 


## Securing your edge endpoint

In the default configuration, the edge endpoint only accepts unencrypted HTTP.  This is not ideal from a security perspective.
Here are different ways you can take to make your edge endpoint secure.

### Limit to localhost

A simple but effective enhancement is to place your SDK workload on the same system as the edge endpoint, and restrict
the endpoint to only listen for connections from localhost (127.0.0.1) instead of any host (0.0.0.0).  Doing this
ensures all traffic is encrypted in transit, which is a key requirement of many security standards.

This can be accomplished in docker with:

```
docker run -d --name groundlight-edge -e GROUNDLIGHT_API_TOKEN --rm -p 127.0.0.1:6717:6717 edge-endpoint
```

### Configuring HTTPS on the NGINX proxy

Because the first server application code reaches is always the NGINX proxy, standard nginx configuration can be used
to configure HTTPS.  You must either supply a signed TLS certificate or generate a self-signed certificate in this case.
When using a self-signed certificate, be sure to configure calling applications to ignore TLS warnings.

To set up TLS, modify the [`nginx.conf`](./configs/nginx.conf) file.  Then rebuild your container and relaunch the server.
