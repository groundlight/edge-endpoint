from app.api.api import IMAGE_QUERIES
from app.api.naming import full_path
from app.schemas.schemas import ImageQueryCreate, ImageQueryResponse

from ..conftest import TestClient
from ..parsing import parse


def test_post_image_queries(test_client: TestClient):
    # TODO: write a better test that accounts for motion detection
    detector_name = "edge-testing"
    image = "https://www.photos-public-domain.com/wp-content/uploads/2010/11/over_flowing_garbage_can.jpg"
    
    url = full_path(IMAGE_QUERIES)
    body = ImageQueryCreate(detector_name=detector_name, image=image, wait=20).dict()

    response = test_client.post(url, json=body)
    parse(response, ImageQueryResponse)
