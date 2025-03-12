from unittest.mock import MagicMock, patch

from app.core.app_state import (
    STALE_METADATA_THRESHOLD_SEC,
    get_detector_metadata,
    refresh_detector_metadata_if_needed,
)
from app.core.utils import TimestampedCache


class MockTimer:
    """
    Mock timer for testing the TimestampedCache class.
    Modified from cachetools _TimedCache._Timer class. Must implement these methods to be compatible with the cache.
    """

    def __init__(self, initial_time=0):
        self.current_time = initial_time
        self.__nesting = 0
        self.__time = initial_time

    def __call__(self):
        if self.__nesting == 0:
            return self.current_time
        else:
            return self.__time

    def __enter__(self):
        if self.__nesting == 0:
            self.__time = time = self.current_time
        else:
            time = self.__time
        self.__nesting += 1
        return time

    def __exit__(self, *exc):
        self.__nesting -= 1

    # Helper method for tests to advance time
    def advance(self, seconds):
        self.current_time += seconds


def test_timestamped_ttl_cache():
    """Test basic functionality of the TimestampedCache class."""
    cache = TimestampedCache(maxsize=100)
    cache["key1"] = "value1"
    assert cache["key1"] == "value1"
    key1_timestamp = cache.get_timestamp("key1")
    assert key1_timestamp is not None

    cache["key2"] = "value2"
    assert cache["key2"] == "value2"
    key2_timestamp = cache.get_timestamp("key2")
    assert key2_timestamp is not None

    assert key1_timestamp < key2_timestamp

    cache["key1"] = "value1_updated"
    assert cache["key1"] == "value1_updated"
    assert cache.get_timestamp("key1") is not None
    key1_timestamp_updated = cache.get_timestamp("key1")
    assert key1_timestamp_updated is not None
    assert key1_timestamp_updated > key1_timestamp


def test_refresh_detector_metadata_if_needed():
    """Test that refresh_detector_metadata_if_needed correctly refreshes the cache if the metadata is stale."""
    mock_gl = MagicMock()
    mock_timer = MockTimer()

    with (
        patch("app.core.utils.time.monotonic", new=mock_timer),  # Enable control over the cache's timer
        patch("app.core.app_state.safe_call_sdk", return_value=MagicMock()) as mock_sdk_call,
    ):
        # First call to populate cache
        detector_id = "test-detector"
        get_detector_metadata(detector_id=detector_id, gl=mock_gl)
        assert mock_sdk_call.call_count == 1

        # Verify no refresh needed when cache is fresh
        refresh_detector_metadata_if_needed(detector_id, mock_gl)
        assert mock_sdk_call.call_count == 1  # Should not have called again

        # Move time forward past the stale threshold
        mock_timer.advance(STALE_METADATA_THRESHOLD_SEC + 1)

        # Now refresh should trigger a new API call
        refresh_detector_metadata_if_needed(detector_id, mock_gl)
        assert mock_sdk_call.call_count == 2  # Should have called again
