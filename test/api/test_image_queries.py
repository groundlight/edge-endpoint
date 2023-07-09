from app.api.api import IMAGE_QUERIES
from app.api.naming import full_path
from app.schemas.schemas import ImageQueryCreate

from ..conftest import TestClient
from ..parsing import parse


def test_post_image_queries(test_client: TestClient):
    # TODO: improve this test
    detector_name = "edge-testing"
    image = "https://www.photos-public-domain.com/wp-content/uploads/2010/11/over_flowing_garbage_can.jpg"

    url = full_path(IMAGE_QUERIES)
    body = ImageQueryCreate(detector_name=detector_name, image=image, wait=20).dict()
    # NOTE: bytes are not JSON-serializable, so this is commented out for now
    # response = test_client.post(url, json=body)


# TODO write unit tests for detectors
