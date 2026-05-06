"""Unit tests for FpsPacer and ErrorBudget."""

import time

from app_benchmark.client import ErrorBudget, FpsPacer


def test_fps_pacer_zero_is_noop():
    pacer = FpsPacer(0)
    t0 = time.perf_counter()
    for _ in range(5):
        pacer.wait()
    assert time.perf_counter() - t0 < 0.05


def test_fps_pacer_paces_to_target():
    pacer = FpsPacer(20)  # 50ms per tick
    t0 = time.perf_counter()
    for _ in range(5):
        pacer.wait()
    elapsed = time.perf_counter() - t0
    # 5 ticks at ~50ms each, allow generous slop.
    assert 0.18 < elapsed < 0.35


def test_error_budget_under_threshold():
    eb = ErrorBudget(threshold_pct=10.0, window_s=30.0)
    now = time.time()
    for i in range(100):
        eb.record(now + i * 0.1, was_error=(i < 5))  # 5% errors
    assert not eb.exceeded()


def test_error_budget_over_threshold():
    eb = ErrorBudget(threshold_pct=5.0, window_s=30.0)
    now = time.time()
    for i in range(100):
        eb.record(now + i * 0.1, was_error=(i < 20))  # 20% errors
    assert eb.exceeded()


def test_error_budget_window_eviction():
    eb = ErrorBudget(threshold_pct=5.0, window_s=10.0)
    base = 1000.0
    # First 50 events all errors, but they're outside the window now.
    for i in range(50):
        eb.record(base + i * 0.1, was_error=True)
    # 50 fresh events, none errors, with timestamps > base + 30 (well outside window).
    for i in range(50):
        eb.record(base + 60 + i * 0.1, was_error=False)
    assert not eb.exceeded()


def test_error_budget_few_events_does_not_trip():
    eb = ErrorBudget(threshold_pct=0.1, window_s=30.0)
    now = time.time()
    for i in range(5):
        eb.record(now + i * 0.1, was_error=True)
    # < 10 events → never trips
    assert not eb.exceeded()
