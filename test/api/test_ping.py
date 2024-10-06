from test.conftest import TestClient
from test.parsing import parse

from app.api.api import PING
from app.api.naming import path_prefix
from app.schemas.ping import Ping


def test_ping(test_client: TestClient):
    url = path_prefix(PING)
    response = test_client.get(url)
    parse(response, Ping)
