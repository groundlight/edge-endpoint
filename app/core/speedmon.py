from collections import deque
import logging

logger = logging.getLogger(__name__)

class SpeedMonitor:
    """Keeps track of how fast inference has been on each model, in a recency window
    """

    def __init__(self, window_size: int = 20):
        self.models = {}
        self.window_size = window_size

    def update(self, model_id: str, elapsed_ms: float):
        if model_id not in self.models:
            self.models[model_id] = deque(maxlen=self.window_size)
        self.models[model_id].append(elapsed_ms)

    def average_fps(self, model_id: str) -> float:
        """Returns 0 if the model has not been updated yet.
        """
        if model_id not in self.models:
            return 0
        N = len(self.models[model_id])
        total_ms = sum(self.models[model_id])
        if total_ms == 0:
            return 1e99
        return 1000 * N / total_ms
