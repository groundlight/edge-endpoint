"""Authorize inbound SDK requests against this Edge Endpoint's Groundlight group."""

import hashlib
from functools import lru_cache

from fastapi import HTTPException, Request
from groundlight import ApiTokenError, Groundlight, GroundlightClientError
from groundlight_openapi_client.exceptions import ApiException
from pydantic import ValidationError

from app.core.groundlight_client import groundlight_client


class EdgeEndpointAuthManager:
    """Authorizes inbound SDK requests by confirming the caller's API token belongs to the
    same Groundlight group as this Edge Endpoint's own device token.

    The caller's token is only ever used to ask cloud who owns it, through a throwaway
    client with rotation disabled, so this cannot interfere with the caller's own token
    rotation. It is never used for substantive work, forwarded upstream, or persisted.
    """

    def __init__(self) -> None:
        self._gl = groundlight_client()
        self._group_id = self._gl.me().group.id
        # TODO: entries never expire, so a token revoked in cloud stays accepted until
        # this process restarts.
        self._validated: set[str] = set()

    def validate_request(self, request: Request) -> None:
        """Raise 401 if the request's token is missing or rejected, 403 if it belongs to
        another group, or 503 if cloud could not be reached to decide."""
        api_token = request.headers.get("x-api-token")
        if not api_token:
            raise HTTPException(status_code=401, detail="Missing x-api-token header.")

        token_hash = hashlib.sha256(api_token.encode()).hexdigest()
        if token_hash in self._validated:
            return

        try:
            group_id = self._group_id_for_token(api_token)
        except ApiTokenError as e:
            raise HTTPException(status_code=401, detail="Invalid API token.") from e
        except (GroundlightClientError, ApiException, ValidationError, AttributeError) as e:
            raise HTTPException(
                status_code=503,
                detail="Unable to validate API token with Groundlight cloud.",
            ) from e

        if group_id != self._group_id:
            raise HTTPException(
                status_code=403,
                detail="API token belongs to a different group than this Edge Endpoint.",
            )
        self._validated.add(token_hash)

    def _group_id_for_token(self, api_token: str) -> str:
        """Ask cloud which group owns this token."""
        # enable_token_rotation=False prevents the Edge Endpoint from rotating the caller's token.
        with Groundlight(api_token=api_token, enable_token_rotation=False) as gl:
            return gl.me().group.id


@lru_cache(maxsize=1)
def edge_endpoint_auth_manager() -> EdgeEndpointAuthManager:
    """Return the process-wide auth manager."""
    return EdgeEndpointAuthManager()


def require_valid_token(request: Request) -> None:
    """FastAPI dependency that rejects requests without a valid same-group API token."""
    edge_endpoint_auth_manager().validate_request(request)
