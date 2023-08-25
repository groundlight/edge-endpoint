from model import ImageQuery


class EdgeDetectorManager:
    """
    Fow now this class is just a container for the IQE cache.
    The cache allows us to control the SDK's polling behavior for image queries
    without having to change the SDK itself.
    """

    def __init__(self) -> None:
        # Cache for image query responses whose IDs start with "iqe_". This is needed
        # because the cloud API does not currently recognize these IDs.
        # This cache maintains a mapping from detector id to iqe
        self.iqe_cache = {}

    def update_cache(self, detector_id: str, image_query: ImageQuery) -> None:
        if detector_id not in self.iqe_cache:
            self.iqe_cache[detector_id] = {}
        self.iqe_cache[detector_id][image_query.id] = image_query

    def get_cached_image_query(self, image_query_id: str) -> ImageQuery | None:
        """
        Searches for the image query across all available detectors.
        It's not ideal that we have to search through all detectors, but this is necessary
        because we don't know which detector the image query belongs to when `gl.get_image_query()`
        is invoked.
        """
        for detector_id in self.iqe_cache:
            if image_query_id in self.iqe_cache[detector_id]:
                return self.iqe_cache[detector_id][image_query_id]
        return None
