# groundlight-edge

Run Groundlight on the edge, as an API endpoint which either handles requests locally or proxies them to the cloud. 
Before running groundlight on the edge, make
sure you have your API token set up in your environment variable 
`GROUNDLIGHT_API_TOKEN`. Checkout [how to create your API token.](https://code.groundlight.ai/python-sdk/docs/getting-started/api-tokens). For more information on 
how to run Groundlight on the edge, checkout our comprehensive [documentation](https://code.groundlight.ai/python-sdk/docs/building-applications/edge)

## Development

### Local (outside docker)

```BASH
# Install
$ poetry install

# Run the server (http://localhost:8080)
# Note: the `--reload` option allows live code changes to be reloaded!
$ poetry run uvicorn --workers 1 --host 0.0.0.0 --port 6717 app.main:app --reload

# Test
$ poetry run pytest
```

### Inside Docker

```BASH
# Build the image
$ docker build --target production-image --tag groundlight-edge .

# Run the server
$ docker run -e GROUNDLIGHT_API_TOKEN=$GROUNDLIGHT_API_TOKEN --rm -it -p 6717:80 groundlight-edge
```

#### See the edge API methods

Open a web browser to http://localhost/redoc. This requires that the application server is already
running either locally or in a docker container. 

#### Call the edge API

Just like with the [SDK](https://code.groundlight.ai/python-sdk/docs/getting-started), Groundlight lets
you build a computer vision system on edge in just a few lines of code. 

```BASH
from groundlight import Groundlight

gl = Groundlight(endpoint="http://localhost:6717")

gl = Groundlight()
det = gl.get_or_create_detector(name="doorway", query="Is the doorway open?")
img = "./docs/static/img/doorway.jpg"  
# Image needs to be converted to a bytestream first
with open(img, "rb") as img_file:
    byte_stream = img_file.read()

image_query = gl.submit_image_query(detector=det, image=byte_stream)
print(f"The answer is {image_query.result}")

```

## Useful references

- [FastAPI](https://fastapi.tiangolo.com)
- [FastAPI in docker](https://fastapi.tiangolo.com/deployment/docker/)
- [FastAPI project structure example](https://github.com/tiangolo/full-stack-fastapi-postgresql)
- [ChatGPT](https://chat.openai.com/chat): It's really good for asking questions like "How do I set up a FastAPI route?", "How do I set up an nginx reverse proxy?", "(code sample) Why is my code not working?", etc.
