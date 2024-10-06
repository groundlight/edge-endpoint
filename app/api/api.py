from fastapi import APIRouter

from app.api.naming import path_prefix, tag
from app.api.routes import health, image_queries, ping

IMAGE_QUERIES = "image-queries"
IMAGE_QUERIES_PREFIX = path_prefix(IMAGE_QUERIES)
IMAGE_QUERIES_TAG = tag(IMAGE_QUERIES)

DETECTORS = "detectors"
DETECTORS_PREFIX = path_prefix(DETECTORS)
DETECTORS_TAG = tag(DETECTORS)

HEALTH = "health"
HEALTH_PREFIX = path_prefix(HEALTH)
HEALTH_TAG = tag(HEALTH)

PING = "ping"
PING_PREFIX = path_prefix(PING)
PING_TAG = tag(PING)

api_router = APIRouter()
api_router.include_router(image_queries.router, prefix=IMAGE_QUERIES_PREFIX, tags=[IMAGE_QUERIES_TAG])
# api_router.include_router(detectors.router, prefix=DETECTORS_PREFIX, tags=[DETECTORS_TAG])

ping_router = APIRouter()
ping_router.include_router(ping.router, prefix=PING_PREFIX, tags=[PING_TAG])

health_router = APIRouter()
health_router.include_router(health.router, prefix=HEALTH_PREFIX, tags=[HEALTH_TAG])
