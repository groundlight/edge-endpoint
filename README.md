# groundlight-edge

Run groundlight on the edge!

## Development

### Local (outside docker)

```BASH
# Install
$ poetry install

# Run the server (http://localhost:8080)
# Note: the `--reload` option allows live code changes to be reloaded!
$ poetry run uvicorn --workers 1 --host 0.0.0.0 --port 8080 app.main:app --reload

# Test
$ poetry run pytest
```

### Inside Docker

```BASH
# Build the image
$ docker build --target production-image --tag groundlight-edge .

# Run the server
$ docker run --rm -it -p 80:80 groundlight-edge
```

#### See the edge API methods

Open a web browser to http://localhost/redoc.

#### Call the edge API

Ping the edge server:

```BASH
$ curl "http://localhost/ping"

{"ping":"Hello!"}
```

Post an image query (this is just a stub for now):

```BASH
$ curl -X POST "http://localhost/device-api/v1/image-queries" \
    --header "Content-Type: application/json" \
    --data '{"detector_id": "abc"}'
```

## Useful references

- [FastAPI](https://fastapi.tiangolo.com)
- [FastAPI in docker](https://fastapi.tiangolo.com/deployment/docker/)
- [FastAPI project structure example](https://github.com/tiangolo/full-stack-fastapi-postgresql)
- [ChatGPT](https://chat.openai.com/chat): It's really good for asking questions like "How do I set up a FastAPI route?", "How do I set up an nginx reverse proxy?", "(code sample) Why is my code not working?", etc.
