"""Tests for the separate_oodd_inference derivation in AppState."""

from unittest.mock import patch

import pytest

from app.core import app_state


@pytest.mark.parametrize(
    ("use_minimal_image", "run_oodd", "expected"),
    [
        (False, True, True),
        (False, False, False),
        (True, True, False),
        (True, False, False),
    ],
)
def test_separate_oodd_inference_derivation(monkeypatch, use_minimal_image, run_oodd, expected):
    monkeypatch.setattr(app_state, "USE_MINIMAL_IMAGE", use_minimal_image)
    monkeypatch.setattr(app_state, "RUN_OODD", run_oodd)

    with (
        patch("app.core.app_state.EdgeInferenceManager"),
        patch("app.core.app_state.DatabaseManager"),
        patch("app.core.app_state.QueueWriter"),
    ):
        state = app_state.AppState()

    assert state.separate_oodd_inference is expected
