from fastapi import FastAPI
from pydantic import BaseModel

app: FastAPI = FastAPI()


class PostImageQueryProps(BaseModel):
    detector_id: str


class PostImageQueryResponse(BaseModel):
    response: str


@app.post("/device-api/v1/image-queries", response_model=PostImageQueryResponse)
def post_image_query(props: PostImageQueryProps):
    return PostImageQueryResponse(response=f"Response for {props.detector_id}!")


class PingResponse(BaseModel):
    ping: str = "Hello!"


@app.get("/ping")
def ping() -> PingResponse:
    return PingResponse()


def get_app():
    return app
