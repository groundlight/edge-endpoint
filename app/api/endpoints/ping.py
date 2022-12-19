from fastapi import APIRouter

from app.schemas.ping import Ping

router = APIRouter()


@router.get("/", response_model=Ping)
async def ping():
    """
    Ping the server to make sure it's running.
    """
    return Ping()
