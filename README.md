# groundlight-edge

Run groundlight on the edge!

### Development

#### Build the image

```BASH
$ docker build --target production-image --tag groundlight-edge .
```

#### Run the server

```BASH
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
