from fastapi import APIRouter

from app.core.groundlight_client import upstream_endpoint
from app.schemas.edge_info import EdgeInfo

router = APIRouter()


@router.get("", response_model=EdgeInfo)
async def get_edge_info():
    """Return details about this Edge Endpoint's deployment, such as which cloud it talks to."""
    return EdgeInfo(upstream_endpoint=upstream_endpoint())
