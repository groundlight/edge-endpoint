import ksuid
from fastapi import Request


def get_groundlight_sdk_instance(request: Request):
    return request.app.state.groundlight


def get_motion_detector_instance(request: Request):
    return request.app.state.motion_detector


def prefixed_ksuid(prefix: str = None) -> str:
    """Returns a unique identifier, with a bunch of nice properties.
    It's statistically guaranteed unique, about as strongly as UUIDv4 are.
    They're sortable by time, approximately, assuming your clocks are sync'd properly.
    They are a single text token, without any hyphens, so you can double-click to select them
    and not worry about your log-search engine (ElasticSearch etc) tokenizing them into parts.
    They can include a semantic prefix such as "chk_" to help identify them.
    They're base62 encoded, so no funny characters, but denser than hex coding of UUID.

    This is just a prefixed KSUID, which is cool.
    """
    if prefix:
        if not prefix.endswith("_"):
            prefix = f"{prefix}_"
    else:
        prefix = ""
    # the "ms" version adds millisecond-level time resolution, at the cost of a equivalent bits of random.
    # Actual collisions remain vanishingly unlikely, and the database would block them if they did happen.
    # But having millisecond resolution is useful in that it means multiple IDs generated during
    # the same request will get ordered properly.
    k = ksuid.KsuidMs()
    out = f"{prefix}{k}"
    return out
