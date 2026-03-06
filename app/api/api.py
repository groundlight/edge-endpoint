from fastapi import APIRouter

from app.api.naming import path_prefix, tag
from app.api.routes import edge_config, health, image_queries, ping

IMAGE_QUERIES = "image-queries"
IMAGE_QUERIES_PREFIX = path_prefix(IMAGE_QUERIES)
IMAGE_QUERIES_TAG = tag(IMAGE_QUERIES)

HEALTH = "health"
HEALTH_PREFIX = path_prefix(HEALTH)
HEALTH_TAG = tag(HEALTH)

PING = "ping"
PING_PREFIX = path_prefix(PING)
PING_TAG = tag(PING)

EDGE_CONFIG = "edge/configure"
EDGE_CONFIG_PREFIX = path_prefix(EDGE_CONFIG)
EDGE_CONFIG_TAG = tag(EDGE_CONFIG)

api_router = APIRouter()
api_router.include_router(image_queries.router, prefix=IMAGE_QUERIES_PREFIX, tags=[IMAGE_QUERIES_TAG])
api_router.include_router(edge_config.router, prefix=EDGE_CONFIG_PREFIX, tags=[EDGE_CONFIG_TAG])

ping_router = APIRouter()
ping_router.include_router(ping.router, prefix=PING_PREFIX, tags=[PING_TAG])

health_router = APIRouter()
health_router.include_router(health.router, prefix=HEALTH_PREFIX, tags=[HEALTH_TAG])
