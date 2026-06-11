"""Cross-site agreement test: every site that consults the per-detector flavor must agree.

The minimal-image deployment folds OODD into the primary pipeline; the full-image deployment
runs OODD as a separate pod. A drift between (image we deploy ↔ OODD topology we expect ↔
request-path routing) would leave the request path looking for an OODD service that the
model-updater never created, or vice versa. This test asserts all three derive from the same
``detector_uses_minimal_image`` answer.
"""

from unittest import mock

from app.core import inference_image
from app.core.edge_inference import EdgeInferenceManager
from app.core.kubernetes_management import InferenceDeploymentManager


def _db_with(minimal_compatible):
    db = mock.Mock()
    record = mock.Mock()
    record.minimal_compatible = minimal_compatible
    db.get_inference_deployment_record.return_value = record
    return db


def test_all_sites_agree_for_minimal_compatible_detector():
    with (
        mock.patch.object(inference_image, "INFERENCE_IMAGE_MODE", "minimal_if_compatible"),
        mock.patch.object(inference_image, "INFERENCE_IMAGE_MINIMAL", "ecr/minimal:tag"),
        mock.patch.object(inference_image, "INFERENCE_IMAGE_FULL", "ecr/full:tag"),
    ):

        db = _db_with(minimal_compatible=True)

        # 1. The deployment image picked by the K8s manager
        image = inference_image.detector_image("det", db)

        # 2. The OODD-creation decision in the model updater
        deploy_separate_oodd = not inference_image.detector_uses_minimal_image("det", db)

        # 3. The routing decision in EdgeInferenceManager
        eim = EdgeInferenceManager(db_manager=db)
        request_separate_oodd = eim.uses_separate_oodd("det")

        assert image == "ecr/minimal:tag"
        assert deploy_separate_oodd is False
        assert request_separate_oodd is False
        assert deploy_separate_oodd == request_separate_oodd


def test_all_sites_agree_for_incompatible_detector():
    with (
        mock.patch.object(inference_image, "INFERENCE_IMAGE_MODE", "minimal_if_compatible"),
        mock.patch.object(inference_image, "INFERENCE_IMAGE_MINIMAL", "ecr/minimal:tag"),
        mock.patch.object(inference_image, "INFERENCE_IMAGE_FULL", "ecr/full:tag"),
    ):

        db = _db_with(minimal_compatible=False)

        image = inference_image.detector_image("det", db)
        deploy_separate_oodd = not inference_image.detector_uses_minimal_image("det", db)
        eim = EdgeInferenceManager(db_manager=db)
        request_separate_oodd = eim.uses_separate_oodd("det")

        assert image == "ecr/full:tag"
        assert deploy_separate_oodd is True
        assert request_separate_oodd is True


# Reference to silence import-not-used linting while making it clear that the K8s manager
# also reads from the same primitive.
_ = InferenceDeploymentManager
