import logging

from fastapi import APIRouter, Body, Depends
from groundlight.edge import EdgeEndpointConfig

from app.core.app_state import AppState, get_app_state
from app.core.edge_config_loader import load_active_config, reconcile_config

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("")
async def get_edge_config():
    """Returns the currently active edge endpoint configuration."""
    return load_active_config().to_payload()


@router.put("")
async def set_edge_config(
    body: dict = Body(...),
    app_state: AppState = Depends(get_app_state),
):
    """Replace the active edge endpoint configuration.

    Diffs against the DB (shared across all workers) rather than in-memory
    state, so this is safe with multiple uvicorn workers.
    """
    new_config = EdgeEndpointConfig.from_payload(body)
    reconcile_config(new_config, app_state.db_manager)
    return new_config.to_payload()
