from fastapi import APIRouter

from app.api.endpoints import image_queries, ping
from app.api.naming import path_prefix, tag

IMAGE_QUERIES = "image-queries"
IMAGE_QUERIES_PREFIX = path_prefix(IMAGE_QUERIES)
IMAGE_QUERIES_TAG = tag(IMAGE_QUERIES)

api_router = APIRouter()
api_router.include_router(image_queries.router, prefix=IMAGE_QUERIES_PREFIX, tags=[IMAGE_QUERIES_TAG])

PING = "ping"
PING_PREFIX = path_prefix(PING)
PING_TAG = tag(PING)

ping_router = APIRouter()
ping_router.include_router(ping.router, prefix=PING_PREFIX, tags=[PING_TAG])
