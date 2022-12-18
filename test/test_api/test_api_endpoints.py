from requests import Response
from app.main import PING_PATH, PingResponse
from starlette import status


def test_ping(test_client):
    response: Response = test_client.get(PING_PATH)

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == PingResponse().dict()
