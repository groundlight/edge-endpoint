"""Cross-site agreement test: every site that consults the per-detector flavor must agree.

The minimal-image deployment folds OODD into the primary pipeline; the full-image deployment
runs OODD as a separate pod. A drift between (image we deploy ↔ OODD topology we expect ↔
request-path routing) would leave the request path looking for an OODD service that the
model-updater never created, or vice versa. This test asserts all three derive from the same
``detector_uses_minimal_image`` answer, including the K8s deployment path which is exercised
by calling the real ``create_inference_deployment`` with I/O mocked out.
"""

from unittest import mock

import pytest

import app.core.edge_inference as ei_mod
from app.core import inference_image
from app.core.edge_inference import EdgeInferenceManager
from app.core.kubernetes_management import InferenceDeploymentManager


@pytest.fixture(autouse=True)
def clear_oodd_cache():
    ei_mod._separate_oodd_cache.clear()
    yield
    ei_mod._separate_oodd_cache.clear()


def _db_with(minimal_compatible):
    db = mock.Mock()
    record = mock.Mock()
    record.minimal_compatible = minimal_compatible
    db.get_inference_deployment_record.return_value = record
    return db


def test_all_sites_agree_for_minimal_compatible_detector():
    with (
        mock.patch.object(inference_image, "INFERENCE_IMAGE_MODE", "minimal_if_compatible"),
        mock.patch.object(inference_image, "MINIMAL_INFERENCE_IMAGE_URI", "ecr/minimal:tag"),
        mock.patch.object(inference_image, "FULL_INFERENCE_IMAGE_URI", "ecr/full:tag"),
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
        mock.patch.object(inference_image, "MINIMAL_INFERENCE_IMAGE_URI", "ecr/minimal:tag"),
        mock.patch.object(inference_image, "FULL_INFERENCE_IMAGE_URI", "ecr/full:tag"),
    ):

        db = _db_with(minimal_compatible=False)

        image = inference_image.detector_image("det", db)
        deploy_separate_oodd = not inference_image.detector_uses_minimal_image("det", db)
        eim = EdgeInferenceManager(db_manager=db)
        request_separate_oodd = eim.uses_separate_oodd("det")

        assert image == "ecr/full:tag"
        assert deploy_separate_oodd is True
        assert request_separate_oodd is True


_MINIMAL_DEPLOYMENT_YAML = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: placeholder-inference-deployment-name
  labels:
    app: placeholder-inference-instance-name
spec:
  selector:
    matchLabels:
      app: placeholder-inference-instance-name
  template:
    metadata: {}
    spec:
      containers:
      - name: main
        image: placeholder-inference-image
"""


def test_k8s_deployment_path_uses_detector_image_primitive():
    """create_inference_deployment derives its image from the same detector_image() primitive as the other sites."""
    with (
        mock.patch.object(inference_image, "INFERENCE_IMAGE_MODE", "minimal_if_compatible"),
        mock.patch.object(inference_image, "MINIMAL_INFERENCE_IMAGE_URI", "ecr/minimal:tag"),
        mock.patch.object(inference_image, "FULL_INFERENCE_IMAGE_URI", "ecr/full:tag"),
        mock.patch.object(InferenceDeploymentManager, "_setup_kube_client"),
        mock.patch.object(
            InferenceDeploymentManager,
            "_load_inference_deployment_template",
            return_value=_MINIMAL_DEPLOYMENT_YAML,
        ),
        mock.patch.object(InferenceDeploymentManager, "_create_from_kube_manifest") as mock_create,
        mock.patch("app.core.kubernetes_management.get_current_model_version", return_value=1),
    ):
        db = _db_with(minimal_compatible=True)
        idm = InferenceDeploymentManager(db_manager=db)
        idm._target_namespace = "test-ns"

        idm.create_inference_deployment("det")

        manifest = mock_create.call_args.kwargs["manifest"]
        assert "ecr/minimal:tag" in manifest
