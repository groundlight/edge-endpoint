from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from app.core.app_state import AppState, get_app_state

router = APIRouter()

# Flag that gets set to True when the App is ready to serve requests
IS_READY = False


@router.get("/live")
async def liveness() -> JSONResponse:
    """
    Check if the server is alive and running.
    This endpoint always returns a 200 status code if the server is operational,
    regardless of the model's loading status or any other internal states.
    Returns:
        JSONResponse: A JSON response with a status of "alive" and a 200 status code.
    """
    return JSONResponse(content={"status": "alive"}, status_code=status.HTTP_200_OK)


@router.get("/ready")
async def readiness(app_state: AppState = Depends(get_app_state)) -> JSONResponse:
    """
    Check if the server is ready to serve requests.
    Returns:
        JSONResponse: A JSON response indicating the readiness status of the model.
            If the model is not loaded, it returns a 503 status code with "not ready" status.
            If the model is loaded, it returns a 200 status code with "ready" status and the model version.
    """
    if not app_state.is_ready:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="not ready")
    return JSONResponse(content={"status": "ready"}, status_code=status.HTTP_200_OK)
