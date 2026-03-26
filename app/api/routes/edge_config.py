import logging

from fastapi import APIRouter, Body, Depends
from groundlight.edge import EdgeEndpointConfig

from app.core.app_state import AppState, get_app_state
from app.core.edge_config_loader import EdgeConfigManager, reconcile_config

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("")
async def get_edge_config():
    """Returns the currently active edge endpoint configuration."""
    return EdgeConfigManager.active().to_payload()


@router.put("")
async def set_edge_config(
    body: dict = Body(...),
    app_state: AppState = Depends(get_app_state),
):
    """Replaces the active edge endpoint configuration with the provided configuration."""
    new_config = EdgeEndpointConfig.from_payload(body)
    reconcile_config(new_config, app_state.db_manager)
    return new_config.to_payload()
