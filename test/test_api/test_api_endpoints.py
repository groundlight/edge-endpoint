from starlette import status

from app.api.api import PING_PREFIX
from app.schemas.ping import Ping

from ..conftest import TestClient


def test_ping(test_client: TestClient):
    assert PING_PREFIX == "/ping"
    response = test_client.get(PING_PREFIX)

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == Ping().dict()
