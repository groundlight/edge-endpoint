from unittest.mock import MagicMock, patch

import pytest

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


def test_timestamped_cache_set_and_get():
    """Test setting and getting values with timestamps in the TimestampedCache."""
    cache = TimestampedCache(maxsize=100)

    # Can set and get a value with its timestamp
    cache["key1"] = "value1"
    assert cache["key1"] == "value1"
    key1_timestamp = cache.get_timestamp("key1")
    assert key1_timestamp is not None

    cache["key2"] = "value2"
    assert cache["key2"] == "value2"
    key2_timestamp = cache.get_timestamp("key2")
    assert key2_timestamp is not None


def test_timestamped_cache_timestamp_ordering():
    """Test that timestamps are ordered correctly in TimestampedCache."""
    cache = TimestampedCache(maxsize=100)

    cache["key1"] = "value1"
    key1_timestamp = cache.get_timestamp("key1")

    cache["key2"] = "value2"
    key2_timestamp = cache.get_timestamp("key2")

    assert key1_timestamp < key2_timestamp


def test_timestamped_cache_update_changes_timestamp():
    """Test that updating a value updates its timestamp."""
    cache = TimestampedCache(maxsize=100)

    cache["key1"] = "value1"
    key1_timestamp = cache.get_timestamp("key1")

    cache["key1"] = "value1_updated"
    assert cache["key1"] == "value1_updated"
    key1_timestamp_updated = cache.get_timestamp("key1")
    assert key1_timestamp_updated is not None
    assert key1_timestamp_updated > key1_timestamp


def test_timestamped_cache_delete_removes_timestamp():
    """Test that deleting an entry removes its timestamp."""
    cache = TimestampedCache(maxsize=100)

    cache["key1"] = "value1"
    assert cache.get_timestamp("key1") is not None

    cache.pop("key1")
    assert cache.get_timestamp("key1") is None


def test_timestamped_cache_suspend_and_restore():
    """Test suspending and restoring a value with timestamp preservation."""
    cache = TimestampedCache(maxsize=100)

    cache["key1"] = "value1"
    key1_timestamp = cache.get_timestamp("key1")
    assert key1_timestamp is not None

    cache.suspend_cached_value("key1")
    assert cache.get("key1", None) is None
    assert cache.get_timestamp("key1") is None

    assert cache.restore_suspended_value("key1")
    assert cache.get("key1", None) == "value1"
    assert cache.get_timestamp("key1") == key1_timestamp


def test_timestamped_cache_delete_suspended_value():
    """Test deleting a suspended value."""
    cache = TimestampedCache(maxsize=100)

    cache["key2"] = "value2"
    cache.suspend_cached_value("key2")
    assert cache.get("key2", None) is None

    assert cache.delete_suspended_value("key2")
    with pytest.raises(KeyError):
        cache.restore_suspended_value("key2")  # Can't restore a deleted suspended value


def test_timestamped_cache_restore_overwrites_existing():
    """Test that restoring a suspended value overwrites any existing value in the cache."""
    cache = TimestampedCache(maxsize=100)

    cache["key3"] = "value3"
    cache.suspend_cached_value("key3")
    assert cache.get("key3", None) is None

    cache["key3"] = "value3_updated"
    cache.restore_suspended_value("key3")
    # TODO is this the desired behavior?
    assert cache.get("key3", None) == "value3"  # Restored value overwrites the updated value


def test_timestamped_cache_suspend_multiple_times():
    """Test suspending a value multiple times."""
    cache = TimestampedCache(maxsize=100)

    cache["key4"] = "value4"
    cache.suspend_cached_value("key4")

    cache["key4"] = "value4_updated"
    cache.suspend_cached_value("key4")

    cache.restore_suspended_value("key4")
    assert cache.get("key4", None) == "value4_updated"


def test_timestamped_cache_error_cases():
    """Test error cases for suspended value operations."""
    cache = TimestampedCache(maxsize=100)

    with pytest.raises(KeyError):
        cache.suspend_cached_value("not_in_cache")  # Can't suspend a value that's not in the cache

    with pytest.raises(KeyError):
        cache.restore_suspended_value("not_in_cache")  # Can't restore a value that hasn't been suspended

    with pytest.raises(KeyError):
        cache.delete_suspended_value("not_in_cache")  # Can't delete a value that hasn't been suspended


def test_refresh_detector_metadata_if_needed_basic():
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


def test_refresh_detector_metadata_if_needed_error():
    """Test that refresh_detector_metadata_if_needed correctly restores the cache if the refresh fails."""
    mock_gl = MagicMock()
    mock_timer = MockTimer()
    mock_metadata = MagicMock()

    with (
        patch("app.core.utils.time.monotonic", new=mock_timer),  # Enable control over the cache's timer
        patch("app.core.app_state.safe_call_sdk", return_value=mock_metadata) as mock_sdk_call,
    ):
        detector_id = "test-detector-2"  # NOTE: the get_detector_metadata cache persists between tests
        # Populate cache
        get_detector_metadata(detector_id=detector_id, gl=mock_gl)
        metadata_cache: TimestampedCache = get_detector_metadata.cache
        assert mock_sdk_call.call_count == 1
        assert "test-detector-2" in metadata_cache
        assert metadata_cache["test-detector-2"] == mock_metadata

        # Move timer forward past the stale threshold
        mock_timer.advance(STALE_METADATA_THRESHOLD_SEC + 1)
        # Cause the call to fetch new metadata to fail
        mock_sdk_call.side_effect = Exception("Error fetching metadata")

        with patch.object(
            metadata_cache, "restore_suspended_value", wraps=metadata_cache.restore_suspended_value
        ) as restore_suspended_value_spy:
            refresh_detector_metadata_if_needed(detector_id, mock_gl)
            assert mock_sdk_call.call_count == 2  # Verify that it tried to refresh the metadata
            # Verify the cache was restored
            assert "test-detector-2" in metadata_cache
            assert metadata_cache["test-detector-2"] == mock_metadata
            # Verify the restore method was called with the correct arguments
            restore_suspended_value_spy.assert_called_once_with(detector_id)
