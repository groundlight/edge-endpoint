from app.api.api import IMAGE_QUERIES
from app.api.naming import full_path
from app.schemas.image_queries import PostImageQueryProps, PostImageQueryResponse

from ..conftest import TestClient
from ..parsing import parse


def test_post_image_queries(test_client: TestClient):
    url = full_path(IMAGE_QUERIES)
    body = PostImageQueryProps(detector_id="abc").dict()

    response = test_client.post(url, json=body)
    parse(response, PostImageQueryResponse)
