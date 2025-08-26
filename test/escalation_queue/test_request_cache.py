import tempfile
import time
from pathlib import Path

import pytest

from app.core.utils import generate_request_id
from app.escalation_queue.constants import DEFAULT_REQUEST_CACHE_MAX_ENTRIES
from app.escalation_queue.request_cache import RequestCache


@pytest.fixture
def temp_cache_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def test_cache(temp_cache_dir: str) -> RequestCache:
    return RequestCache(cache_dir=temp_cache_dir, max_entries=DEFAULT_REQUEST_CACHE_MAX_ENTRIES)


def test_initialization_creates_directory(temp_cache_dir: str):
    """Verify that initialization creates the cache directory if it does not exist."""
    cache_dir = Path(temp_cache_dir) / "subdir"
    assert not cache_dir.exists()

    RequestCache(str(cache_dir), max_entries=DEFAULT_REQUEST_CACHE_MAX_ENTRIES)
    assert cache_dir.exists()
    assert cache_dir.is_dir()


def test_add_and_contains(test_cache: RequestCache):
    """Verify that adding a request ID creates the file and `contains` returns True."""
    req_id = generate_request_id()
    assert not test_cache.contains(req_id)

    test_cache.add(req_id)

    assert test_cache.contains(req_id)
    assert (Path(test_cache.cache_dir) / req_id).is_file()


def test_add_duplicate_does_not_duplicate(test_cache: RequestCache):
    """Verify that adding the same request ID twice does not create duplicates."""
    req_id = generate_request_id()
    test_cache.add(req_id)
    test_cache.add(req_id)

    files = list(Path(test_cache.cache_dir).iterdir())
    assert len(files) == 1
    assert files[0].name == req_id


def test_contains_returns_false_for_missing(test_cache: RequestCache):
    """Verify that `contains` returns False for a request ID that is not in the cache."""
    assert not test_cache.contains(generate_request_id())


def test_eviction_of_oldest(test_cache: RequestCache):
    """Verify that the oldest entry is evicted when `max_entries` is exceeded."""
    req_ids = [generate_request_id() for _ in range(test_cache.max_entries)]
    for req_id in req_ids:
        test_cache.add(req_id)
        time.sleep(0.01)  # Ensure unique mtime for each file to make the test deterministic.

    for req_id in req_ids:
        assert test_cache.contains(req_id)

    new_req_id = generate_request_id()
    test_cache.add(new_req_id)
    assert not test_cache.contains(req_ids[0])

    for req_id in req_ids[1:]:
        assert test_cache.contains(req_id)
    assert test_cache.contains(new_req_id)
    files = list(Path(test_cache.cache_dir).iterdir())
    assert len(files) == test_cache.max_entries


def test_eviction_handles_overfull_directory(temp_cache_dir: str):
    """Verify that if the directory is overfull when instantiated, eviction occurs on add."""
    # Use a large max_entries to add files first
    large_cache = RequestCache(temp_cache_dir, max_entries=6)
    req_ids = [generate_request_id() for _ in range(5)]
    for req_id in req_ids:
        large_cache.add(req_id)

    # Now re-instantiate with a smaller max_entries
    small_cache = RequestCache(temp_cache_dir, max_entries=3)
    new_req_id = generate_request_id()
    small_cache.add(new_req_id)

    files = sorted(f.name for f in Path(temp_cache_dir).iterdir())
    assert len(files) == small_cache.max_entries
    assert new_req_id in files


def test_persistence_between_instances(temp_cache_dir: str):
    """Verify that cache entries persist between different RequestCache instances."""
    cache1 = RequestCache(temp_cache_dir, max_entries=2)
    req_a = generate_request_id()
    req_b = generate_request_id()
    cache1.add(req_a)
    assert cache1.contains(req_a)

    cache2 = RequestCache(temp_cache_dir, max_entries=2)
    assert cache2.contains(req_a)
    cache2.add(req_b)
    assert cache2.contains(req_b)

    cache3 = RequestCache(temp_cache_dir, max_entries=2)
    assert cache3.contains(req_a)
    assert cache3.contains(req_b)
