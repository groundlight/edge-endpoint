"""Per-detector inference image flavor selection.

Three modes set globally via ``INFERENCE_IMAGE_MODE``. The concrete container image URIs
for each flavor are ``FULL_INFERENCE_IMAGE_URI`` and ``MINIMAL_INFERENCE_IMAGE_URI``
(set by Helm from registry + tag):

- ``standard``: every detector runs on the full image.
- ``minimal_if_compatible``: per-detector — minimal when the cloud reported
  ``minimal_compatible=True``, full otherwise.
- ``fully_minimal``: every detector runs on the minimal image.

``minimal_compatible`` is persisted on the primary ``InferenceDeployment`` row by
the model-updater after each fetch-model-urls cycle. The same selection is the
single signal for both the deployment image (minimal vs full) and whether to run
OODD as a separate pod (full → yes, minimal → folded into primary), so all
three call sites — model-updater, ``EdgeInferenceManager.run_inference``, and
deletion path — derive from this module and stay in agreement.
"""

import logging
import os

from app.core.database import DatabaseManager

logger = logging.getLogger(__name__)

MODE_STANDARD = "standard"
MODE_MINIMAL_IF_COMPATIBLE = "minimal_if_compatible"
MODE_FULLY_MINIMAL = "fully_minimal"

VALID_MODES = {MODE_STANDARD, MODE_MINIMAL_IF_COMPATIBLE, MODE_FULLY_MINIMAL}

INFERENCE_IMAGE_MODE = os.environ.get("INFERENCE_IMAGE_MODE", MODE_STANDARD)
if INFERENCE_IMAGE_MODE not in VALID_MODES:
    raise ValueError(
        f"INFERENCE_IMAGE_MODE={INFERENCE_IMAGE_MODE!r} is not one of {sorted(VALID_MODES)}. "
        "The helm chart enforces this via values.schema.json; an invalid value here means the "
        "env var was set manually outside of helm."
    )

FULL_INFERENCE_IMAGE_URI = os.environ.get("FULL_INFERENCE_IMAGE_URI", "")
MINIMAL_INFERENCE_IMAGE_URI = os.environ.get("MINIMAL_INFERENCE_IMAGE_URI", "")


def detector_uses_minimal_image(detector_id: str, db_manager: DatabaseManager) -> bool:
    """Whether ``detector_id`` should run on the minimal inference image."""
    if INFERENCE_IMAGE_MODE == MODE_FULLY_MINIMAL:
        return True
    if INFERENCE_IMAGE_MODE == MODE_STANDARD:
        return False
    record = db_manager.get_inference_deployment_record(detector_id, is_oodd=False)
    return bool(record and record.minimal_compatible)


def detector_image(detector_id: str, db_manager: DatabaseManager) -> str:
    """The fully-qualified inference image (incl. tag) for ``detector_id``."""
    return MINIMAL_INFERENCE_IMAGE_URI if detector_uses_minimal_image(detector_id, db_manager) else FULL_INFERENCE_IMAGE_URI
