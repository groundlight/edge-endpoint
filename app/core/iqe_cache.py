from cachetools import LRUCache
from model import ImageQuery


class IQECache:
    """
    The cache allows us to control the SDK's polling behavior for image queries
    without having to change the SDK itself.

    Note(on default cache size): Assuming a 16GB RAM machine and assuming further that
    we want to use at most 1/10 of the available RAM for the cache, we will need
    approximately 1,000,000 entries in the cache before we start evicting old entries.

    """

    def __init__(self, cache_size=1_000_000) -> None:
        # Cache for image query responses whose IDs are prefixed with "iqe_". This is needed
        # because the cloud API does not currently recognize such IDs.
        # The cache maintains a mapping from "iqe"'s to image query objects.
        # NOTE: This cache is not thread-safe and it is global across all detectors.
        self.global_cache = LRUCache(maxsize=cache_size)

    def get_cached_image_query(self, image_query_id: str) -> ImageQuery | None:
        return self.global_cache.get(image_query_id, None)

    def update_cache(self, image_query: ImageQuery) -> None:
        if image_query.id in self.global_cache:
            return

        # Add to the global cache.
        self.global_cache[image_query.id] = image_query

    def __str__(self) -> str:
        return str(self.global_cache)