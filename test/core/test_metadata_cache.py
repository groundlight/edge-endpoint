import threading
from contextlib import contextmanager
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


@pytest.fixture
def mock_timer():
    """Controls the clock used by the detector metadata cache and its refresh."""
    timer = MockTimer()
    with patch("app.core.utils.time.monotonic", new=timer):
        yield timer


@pytest.fixture(autouse=True)
def clear_detector_metadata_cache():
    """The detector metadata cache is module-level, so isolate it per test."""
    get_detector_metadata.cache.clear()
    yield
    get_detector_metadata.cache.clear()


@contextmanager
def mock_cloud(**sdk_kwargs):
    """Patch the cloud detector lookup made by get_detector_metadata; yields the SDK-call mock."""
    with (
        patch("app.core.app_state.groundlight_client", return_value=MagicMock()),
        patch("app.core.app_state.safe_call_sdk", **sdk_kwargs) as mock_sdk_call,
    ):
        yield mock_sdk_call


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


def test_timestamped_cache_touch_updates_timestamp_and_keeps_value(mock_timer):
    """Touching a key re-stamps it to now without changing its value."""
    cache = TimestampedCache(maxsize=100)
    cache["key1"] = "value1"
    mock_timer.advance(10)

    cache.touch("key1")

    assert cache["key1"] == "value1"
    assert cache.get_timestamp("key1") == mock_timer.current_time


def test_timestamped_cache_touch_missing_key_is_noop():
    """Touching a key that is not cached does not add it."""
    cache = TimestampedCache(maxsize=100)

    cache.touch("not_in_cache")

    assert "not_in_cache" not in cache
    assert cache.get_timestamp("not_in_cache") is None


def test_refresh_detector_metadata_if_needed_basic(mock_timer):
    """A refresh only reaches the cloud once the cached metadata is older than the stale threshold."""
    detector_id = "test-detector"

    with mock_cloud(return_value=MagicMock()) as mock_sdk_call:
        get_detector_metadata(detector_id=detector_id)
        assert mock_sdk_call.call_count == 1

        refresh_detector_metadata_if_needed(detector_id)
        assert mock_sdk_call.call_count == 1  # still fresh

        mock_timer.advance(STALE_METADATA_THRESHOLD_SEC + 1)
        refresh_detector_metadata_if_needed(detector_id)
        assert mock_sdk_call.call_count == 2


def test_cached_value_served_while_refresh_in_flight(mock_timer):
    """While a refresh is fetching, lookups keep returning the cached value without calling the cloud."""
    detector_id = "det_served_during_refresh"
    old, new = MagicMock(name="old"), MagicMock(name="new")
    metadata_cache: TimestampedCache = get_detector_metadata.cache
    observed = {}
    phase = "populate"

    def cloud(*_args, **_kwargs):
        nonlocal phase
        if phase == "populate":
            return old
        if phase == "fetching":
            raise ConnectionError("a lookup reached the cloud while the refresh was in flight")
        phase = "fetching"
        # Assertions raised here would be swallowed by the refresh, so record what a request sees instead.
        observed["cached"] = metadata_cache.get(detector_id)
        try:
            observed["served"] = get_detector_metadata(detector_id=detector_id)
        except Exception as e:  # noqa: BLE001
            observed["served"] = e
        return new

    with mock_cloud(side_effect=cloud) as mock_sdk_call:
        get_detector_metadata(detector_id=detector_id)
        mock_timer.advance(STALE_METADATA_THRESHOLD_SEC + 1)
        phase = "refresh"

        refresh_detector_metadata_if_needed(detector_id)

    assert observed["cached"] is old
    assert observed["served"] is old
    assert mock_sdk_call.call_count == 2  # populate + the refresh; the lookup during the refresh hit the cache
    assert metadata_cache[detector_id] is new


@pytest.mark.parametrize("error", [Exception("cloud error"), ConnectionError("cloud unreachable")])
def test_failed_refresh_keeps_value_and_backs_off(mock_timer, error):
    """A failed refresh keeps the cached value and waits a full stale interval before retrying."""
    detector_id = "det_failed_refresh"
    old = MagicMock(name="old")
    metadata_cache: TimestampedCache = get_detector_metadata.cache

    with mock_cloud(return_value=old) as mock_sdk_call:
        get_detector_metadata(detector_id=detector_id)
        mock_timer.advance(STALE_METADATA_THRESHOLD_SEC + 1)
        mock_sdk_call.side_effect = error

        refresh_detector_metadata_if_needed(detector_id)

        assert mock_sdk_call.call_count == 2
        assert metadata_cache[detector_id] is old
        assert metadata_cache.get_timestamp(detector_id) == mock_timer.current_time

        mock_timer.advance(STALE_METADATA_THRESHOLD_SEC - 1)
        refresh_detector_metadata_if_needed(detector_id)
        assert mock_sdk_call.call_count == 2  # still backing off

        mock_timer.advance(2)
        refresh_detector_metadata_if_needed(detector_id)
        assert mock_sdk_call.call_count == 3  # retried once the backoff elapsed
        assert metadata_cache[detector_id] is old


def test_successful_refresh_overwrites_value(mock_timer):
    """A successful refresh replaces the cached value and its timestamp."""
    detector_id = "det_successful_refresh"
    old, new = MagicMock(name="old"), MagicMock(name="new")
    metadata_cache: TimestampedCache = get_detector_metadata.cache

    with mock_cloud(return_value=old) as mock_sdk_call:
        get_detector_metadata(detector_id=detector_id)
        mock_timer.advance(STALE_METADATA_THRESHOLD_SEC + 1)
        mock_sdk_call.return_value = new

        refresh_detector_metadata_if_needed(detector_id)

    assert metadata_cache[detector_id] is new
    assert metadata_cache.get_timestamp(detector_id) == mock_timer.current_time


def test_concurrent_refreshes_are_deduplicated(mock_timer):
    """Only one refresh per detector reaches the cloud at a time; the others return immediately."""
    detector_id = "det_concurrent_refresh"
    old, new = MagicMock(name="old"), MagicMock(name="new")
    metadata_cache: TimestampedCache = get_detector_metadata.cache
    fetch_started, release_fetch = threading.Event(), threading.Event()

    def slow_cloud(*_args, **_kwargs):
        fetch_started.set()
        release_fetch.wait(timeout=5)
        return new

    with mock_cloud(return_value=old) as mock_sdk_call:
        get_detector_metadata(detector_id=detector_id)
        mock_timer.advance(STALE_METADATA_THRESHOLD_SEC + 1)
        mock_sdk_call.side_effect = slow_cloud

        first = threading.Thread(target=refresh_detector_metadata_if_needed, args=(detector_id,))
        first.start()
        try:
            assert fetch_started.wait(timeout=5)
            second = threading.Thread(target=refresh_detector_metadata_if_needed, args=(detector_id,))
            second.start()
            second.join(timeout=5)
            assert not second.is_alive(), "a concurrent refresh blocked instead of returning"
            refresh_detector_metadata_if_needed(detector_id)
        finally:
            release_fetch.set()
            first.join(timeout=5)

        assert not first.is_alive()
        assert mock_sdk_call.call_count == 2  # populate + exactly one refresh
        assert metadata_cache[detector_id] is new
