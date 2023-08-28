from cachetools import LRUCache
from model import ImageQuery


class EdgeDetectorManager:
    """
    For now this class is just a container for the IQE cache.
    The cache allows us to control the SDK's polling behavior for image queries
    without having to change the SDK itself.

    Note(on default cache size): Assuming a 16GB RAM machine and assuming further that
    we want to use at most 1/10 of the available RAM for the cache, we will need
    approximately 1,000,000 entries in the cache before we start evicting old entries.

    """

    def __init__(self, cache_size=1000000) -> None:
        # Cache for image query responses whose IDs are prefixed with "iqe_". This is needed
        # because the cloud API does not currently recognize such IDs.
        # The cache maintains a mapping from detector id to image query id, and each
        # image query id is mapped to a corresponding image query.
        self.detectors = {}

        # Global LRU cache. This is useful for evicting old entries by considering recency across
        # all detectors. It might be the case that one detector is more active than others, so we
        # would want to evict entries from other detectors first. A global cache across detectors
        # allows us to do this.

        self.global_cache = LRUCache(maxsize=cache_size)

    def get_cached_image_query(self, image_query_id: str) -> ImageQuery | None:
        detector_id = self.global_cache.get(image_query_id, None)
        if detector_id:
            return self.detectors[detector_id][image_query_id]

        return None

    def update_cache(self, detector_id: str, image_query: ImageQuery) -> None:
        if image_query.id in self.global_cache:
            return

        # Add to the global cache.
        self.global_cache[image_query.id] = detector_id

        # Add/Update in the detector cache.
        if detector_id not in self.detectors:
            self.detectors[detector_id] = {}
        self.detectors[detector_id][image_query.id] = image_query

        # Handle eviction from global cache data structure.
        if len(self.global_cache) >= self.global_cache.maxsize:
            evicted_image_query_id, evicted_detector_id = self.global_cache.popitem(last=False)
            if evicted_detector_id in self.detectors and evicted_image_query_id in self.detectors[evicted_detector_id]:
                del self.detectors[evicted_detector_id][evicted_image_query_id]

    def __str__(self) -> str:
        return str(self.detectors)


# class EdgeDetectorManager:
#     """
#     Fow now this class is just a container for the IQE cache.
#     The cache allows us to control the SDK's polling behavior for image queries
#     without having to change the SDK itself.
#     """

#     def __init__(self) -> None:
#         # Cache for image query responses whose IDs start with "iqe_". This is needed
#         # because the cloud API does not currently recognize these IDs.
#         # This cache maintains a mapping from detector id to iqe, and each
#         # iqe is mapped to a corresponding image query.
#         self.iqe_cache = {}

#     def update_cache(self, detector_id: str, image_query: ImageQuery) -> None:
#         if detector_id not in self.iqe_cache:
#             self.iqe_cache[detector_id] = {}
#         self.iqe_cache[detector_id][image_query.id] = image_query

#     def get_cached_image_query(self, image_query_id: str) -> ImageQuery | None:
#         """
#         Searches for the image query across all available detectors.
#         It's not ideal that we have to search through all detectors, but this is necessary
#         because we don't know which detector the image query belongs to when `gl.get_image_query()`
#         is invoked.
#         """
#         for detector_id in self.iqe_cache:
#             if image_query_id in self.iqe_cache[detector_id]:
#                 return self.iqe_cache[detector_id][image_query_id]
#         return None
