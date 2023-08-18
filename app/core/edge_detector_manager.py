class EdgeDetectorManager:
    """
    Fow now this class is just a container for the IQE cache.
    The cache allows us to control the SDK's polling behavior for image queries
    without having to change the SDK itself.
    """

    def __init__(self) -> None:
        # Cache for image query responses whose IDs start with "iqe_". This is needed
        # because the cloud API does not currently recognize these IDs.
        self.iqe_cache = {}
