# Groundlight Edge Endpoint

Run your Groundlight models on-prem by hosting an Edge Endpoint on your own hardware.  The Edge Endpoint exposes the exact same API as the Groundlight cloud service, so any Groundlight application can point to the Edge Endpoint simply by configuring the `GROUNDLIGHT_ENDPOINT` environment variable as follows:

```
GROUNDLIGHT_ENDPOINT=http://localhost:6717
# This assumes your Groundlight SDK application is running on the same host as the Edge Endpoint.
```

The Edge Endpoint will attempt to answer image queries using local models for your detectors.  If it can do so confidently, you get faster cheaper responses.  But if it can't, it will escalate the image queries to the cloud for further analysis.

Before running groundlight on the edge, make
sure you have your API token set up in your environment variable 
`GROUNDLIGHT_API_TOKEN`. Checkout [how to create your API token.](https://code.groundlight.ai/python-sdk/docs/getting-started/api-tokens). For more information on 
how to run Groundlight on the edge, checkout our [documentation](https://code.groundlight.ai/python-sdk/docs/building-applications/edge)

## Running the Edge Endpoint

The recommended way to run the Edge Endpoint is inside a docker container as follows:

```bash
docker build --target production-image --tag edge-endpoint .

# Run the server
docker run -e GROUNDLIGHT_API_TOKEN --rm -it -p 6717:6717 edge-endpoint
```

### Using the Edge Endpoint with your Groundlight application.

Any application written with the [Groundlight SDK](https://pypi.org/project/groundlight/) can work with an Edge Endpoint without any code changes.  Simply set an environment variable with the URL of your Edge Endpoint like:

```bash
export GROUNDLIGHT_ENDPOINT=http://localhost:6717
```

But if you'd like more control, you can also initialize the `Groundlight` SDK object with the endpoint explicitly like this:

```python
from groundlight import Groundlight

gl = Groundlight(endpoint="http://localhost:6717")

gl = Groundlight()
det = gl.get_or_create_detector(name="doorway", query="Is the doorway open?")
img = "./docs/static/img/doorway.jpg"  
with open(img, "rb") as img_file:
    byte_stream = img_file.read()

image_query = gl.submit_image_query(detector=det, image=byte_stream)
print(f"The answer is {image_query.result}")
```

See the [SDK's getting started guide](https://code.groundlight.ai/python-sdk/docs/getting-started) for more info.

## Development

### Common Terms 

* `Edge logic server:` This is running on `http://localhost:6718` inside the docker container. 
* `NGINX proxy:` This is the proxy server through which we access the edge logic server. It runs on `http://localhost:6717`.
* `Cloud API:` This is the upstream API that we use as a fallback in case the edge logic server encounters problems. It is set to `https://api.groundlight.ai`. 
* `Edge endpoint:` This is the user-visible endpoint (i.e., the upstream you can set for the Groundlight application). This is set to `http://localhost:6717`. 


### Local (outside docker)

To develop outside docker, you need to run both the nginx proxy and the edge logic server.

The easiest way to run the nginx proxy is:

```BASH
# cd to the root of this repo
sudo nginx -c $(pwd)/configs/nginx.conf
```

Then you must run the edge logic server like this:

```BASH
# Install
poetry install

# Run the server (http://localhost:6718)
# Note: the `--reload` option allows live code changes to be reloaded!
poetry run uvicorn --workers 1 --host 0.0.0.0 --port 6718 app.main:app --reload

# Test
poetry run pytest
```

### See the edge API methods

Open a web browser to http://localhost/redoc. This requires that the application server is already
running either locally or in a docker container. 

