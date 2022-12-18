from fastapi import FastAPI
from pydantic import BaseModel

app: FastAPI = FastAPI()


class PostImageQueryProps(BaseModel):
    detector_id: str


class PostImageQueryResponse(BaseModel):
    response: str


API_PATH = "/device-api/v1"
POST_IMAGE_QUERY_PATH = f"{API_PATH}/image-queries"


@app.post(POST_IMAGE_QUERY_PATH, response_model=PostImageQueryResponse)
def post_image_query(props: PostImageQueryProps):
    return PostImageQueryResponse(response=f"Response for {props.detector_id}!")


DEFAULT_PING_RESPONSE = "Hello!"


class PingResponse(BaseModel):
    message: str = DEFAULT_PING_RESPONSE


PING_PATH = "/ping"


@app.get(PING_PATH, response_model=PingResponse)
def ping() -> PingResponse:
    return PingResponse()


def get_app():
    return app
