"""Unit tests for EdgeEndpointAuthManager request validation."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from groundlight import ApiTokenError, GroundlightClientError
from groundlight_openapi_client.exceptions import ApiException
from pydantic import ValidationError
from starlette.requests import Request

from app.core.edge_endpoint_auth import EdgeEndpointAuthManager


def _request_with_token(token: str | None) -> Request:
    headers = []
    if token is not None:
        headers.append((b"x-api-token", token.encode()))
    scope = {"type": "http", "method": "GET", "path": "/", "headers": headers}
    return Request(scope)


@pytest.fixture
def auth_manager() -> EdgeEndpointAuthManager:
    """Build an auth manager with a mocked device client and fixed group id."""
    with patch("app.core.edge_endpoint_auth.groundlight_client") as mock_device_client:
        mock_gl = MagicMock()
        mock_gl.me.return_value.group.id = "group-edge"
        mock_device_client.return_value = mock_gl
        manager = EdgeEndpointAuthManager()
    manager._validated.clear()
    return manager


def test_missing_token_returns_401(auth_manager: EdgeEndpointAuthManager):
    with pytest.raises(HTTPException) as exc_info:
        auth_manager.validate_request(_request_with_token(None))
    assert exc_info.value.status_code == 401


def test_invalid_token_returns_401(auth_manager: EdgeEndpointAuthManager):
    with patch.object(auth_manager, "_group_id_for_token", side_effect=ApiTokenError("bad token")):
        with pytest.raises(HTTPException) as exc_info:
            auth_manager.validate_request(_request_with_token("tok_bad"))
    assert exc_info.value.status_code == 401
    assert len(auth_manager._validated) == 0  # rejections are not cached


def test_cloud_unreachable_returns_503(auth_manager: EdgeEndpointAuthManager):
    with patch.object(auth_manager, "_group_id_for_token", side_effect=GroundlightClientError("down")):
        with pytest.raises(HTTPException) as exc_info:
            auth_manager.validate_request(_request_with_token("tok_ok"))
    assert exc_info.value.status_code == 503


def test_api_exception_from_me_returns_503(auth_manager: EdgeEndpointAuthManager):
    with patch.object(auth_manager, "_group_id_for_token", side_effect=ApiException(status=500, reason="boom")):
        with pytest.raises(HTTPException) as exc_info:
            auth_manager.validate_request(_request_with_token("tok_ok"))
    assert exc_info.value.status_code == 503


def test_malformed_me_payload_returns_503(auth_manager: EdgeEndpointAuthManager):
    with patch.object(
        auth_manager,
        "_group_id_for_token",
        side_effect=ValidationError.from_exception_data("Me", []),
    ):
        with pytest.raises(HTTPException) as exc_info:
            auth_manager.validate_request(_request_with_token("tok_ok"))
    assert exc_info.value.status_code == 503


def test_other_group_returns_403(auth_manager: EdgeEndpointAuthManager):
    with patch.object(auth_manager, "_group_id_for_token", return_value="group-other"):
        with pytest.raises(HTTPException) as exc_info:
            auth_manager.validate_request(_request_with_token("tok_other"))
    assert exc_info.value.status_code == 403


def test_same_group_accepted_and_cached(auth_manager: EdgeEndpointAuthManager):
    with patch.object(auth_manager, "_group_id_for_token", return_value="group-edge") as mock_lookup:
        auth_manager.validate_request(_request_with_token("tok_same"))
        auth_manager.validate_request(_request_with_token("tok_same"))
    assert mock_lookup.call_count == 1
