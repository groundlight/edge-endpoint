from typing import Type, TypeVar

from httpx import Response
from pydantic import BaseModel
from starlette import status

T = TypeVar("T", bound=BaseModel)


def parse(response: Response, schema: Type[T], status_code: int = status.HTTP_200_OK) -> T:
    """
    Parse the response using a pydantic schema. Raises an exception if the response is not valid under
    the schema.

    Returns the pydantic model instance.
    """
    assert response.status_code == status_code, f"Expected {status_code=}, got {response.status_code=}"

    d = response.json()  # This will raise an exception if the response is not valid JSON
    schema.validate(d)  # This will raise an exception if the response is not valid under the given schema

    return schema(**d)
