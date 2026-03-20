import logging

from fastapi import APIRouter, Depends

from app.core.app_state import AppState, get_app_state

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("")
async def get_edge_config(app_state: AppState = Depends(get_app_state)):
    """Returns the currently active edge endpoint configuration."""
    return app_state.edge_config.to_payload()
