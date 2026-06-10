"""Unit tests for the per-detector flavor logic in the model updater.

These tests drive ``_check_new_models_and_inference_deployments`` for individual detectors
with their image flavor flipped on and off, including the hot-swap path and a crash-recovery
case. They mock every K8s/DB/IO surface so the loop runs in-process.
"""

from unittest import mock

import pytest

from app.core import inference_image
from app.model_updater import update_models


def _detector_record(detector_id, minimal_compatible):
    rec = mock.Mock()
    rec.detector_id = detector_id
    rec.minimal_compatible = minimal_compatible
    return rec


def _make_db(records_by_did_and_oodd):
    """records_by_did_and_oodd: {(detector_id, is_oodd): record_or_None}."""
    db = mock.Mock()

    def get_record(detector_id, is_oodd=False):
        return records_by_did_and_oodd.get((detector_id, is_oodd))

    db.get_inference_deployment_record.side_effect = get_record

    def update_record(model_name, fields_to_update):
        # Find the matching record (model_name encodes detector_id + primary/oodd)
        for (did, oodd), rec in records_by_did_and_oodd.items():
            if rec is None:
                continue
            from app.core.naming import get_edge_inference_model_name

            if get_edge_inference_model_name(did, is_oodd=oodd) == model_name:
                for k, v in fields_to_update.items():
                    setattr(rec, k, v)
                return

    db.update_inference_deployment_record.side_effect = update_record
    return db


def _make_deployment_manager(initial_images=None):
    """A deployment_manager mock that tracks the current 'image' for each deployment name.

    initial_images: {deployment_name: image} for pre-existing deployments.
    """
    state = dict(initial_images or {})
    mgr = mock.Mock()

    def get_inference_deployment(deployment_name):
        if deployment_name in state:
            d = mock.Mock()
            d.spec.template.spec.containers = [mock.Mock(name="inference-server", image=state[deployment_name])]
            return d
        return None

    def get_deployment_image(deployment_name):
        return state.get(deployment_name)

    def create(detector_id, is_oodd=False):
        from app.core.naming import get_edge_inference_deployment_name

        name = get_edge_inference_deployment_name(detector_id, is_oodd=is_oodd)
        # Whatever the per-detector image is at the moment of creation:
        state[name] = mgr._desired_image_for_create(detector_id, is_oodd)

    def delete(detector_id, is_oodd=False):
        from app.core.naming import get_edge_inference_deployment_name

        state.pop(get_edge_inference_deployment_name(detector_id, is_oodd=is_oodd), None)

    def fully_deleted(detector_id, is_oodd=False):
        from app.core.naming import get_edge_inference_deployment_name

        return get_edge_inference_deployment_name(detector_id, is_oodd=is_oodd) not in state

    def rollout_complete(deployment_name):
        return deployment_name in state

    mgr.get_inference_deployment.side_effect = get_inference_deployment
    mgr.get_deployment_image.side_effect = get_deployment_image
    mgr.create_inference_deployment.side_effect = create
    mgr.delete_inference_deployment.side_effect = delete
    mgr.is_inference_deployment_fully_deleted.side_effect = fully_deleted
    mgr.is_inference_deployment_rollout_complete.side_effect = rollout_complete
    mgr.update_inference_deployment.return_value = True
    mgr._state = state  # for test inspection
    return mgr


FULL = "ecr/gl-edge-inference:tag"
MINIMAL = "ecr/gl-edge-inference-minimal:tag"


@pytest.fixture(autouse=True)
def _pin_images():
    with (
        mock.patch.object(inference_image, "INFERENCE_IMAGE_FULL", FULL),
        mock.patch.object(inference_image, "INFERENCE_IMAGE_MINIMAL", MINIMAL),
    ):
        yield


@pytest.fixture
def edge_inference_manager_returning():
    """Build an edge_inference_manager mock whose update_models_if_available returns a fixed value."""

    def _build(new_model: bool, minimal_compatible: bool):
        m = mock.Mock()
        m.update_models_if_available.return_value = (new_model, minimal_compatible)
        m.MODEL_REPOSITORY = "/tmp/no-such-path"
        return m

    return _build


class TestPerDetectorFlavor:
    def test_minimal_compatible_detector_gets_minimal_image_no_oodd(self, edge_inference_manager_returning):
        with mock.patch.object(inference_image, "INFERENCE_IMAGE_MODE", "minimal_if_compatible"):
            db = _make_db({("detA", False): _detector_record("detA", False)})
            dm = _make_deployment_manager()
            dm._desired_image_for_create = lambda did, oodd: MINIMAL  # detA flips to minimal_compatible=True

            eim = edge_inference_manager_returning(new_model=True, minimal_compatible=True)
            update_models._check_new_models_and_inference_deployments(
                detector_id="detA", edge_inference_manager=eim, deployment_manager=dm, db_manager=db
            )

            from app.core.naming import get_edge_inference_deployment_name

            primary_name = get_edge_inference_deployment_name("detA", is_oodd=False)
            oodd_name = get_edge_inference_deployment_name("detA", is_oodd=True)
            assert dm._state.get(primary_name) == MINIMAL
            assert oodd_name not in dm._state  # no separate OODD pod for a minimal-image detector

    def test_incompatible_detector_gets_full_image_and_oodd(self, edge_inference_manager_returning):
        with mock.patch.object(inference_image, "INFERENCE_IMAGE_MODE", "minimal_if_compatible"):
            db = _make_db(
                {("detB", False): _detector_record("detB", False), ("detB", True): _detector_record("detB", None)}
            )
            dm = _make_deployment_manager()
            dm._desired_image_for_create = lambda did, oodd: FULL

            eim = edge_inference_manager_returning(new_model=True, minimal_compatible=False)
            update_models._check_new_models_and_inference_deployments(
                detector_id="detB", edge_inference_manager=eim, deployment_manager=dm, db_manager=db
            )

            from app.core.naming import get_edge_inference_deployment_name

            assert dm._state.get(get_edge_inference_deployment_name("detB", is_oodd=False)) == FULL
            assert dm._state.get(get_edge_inference_deployment_name("detB", is_oodd=True)) == FULL


class TestHotSwap:
    def test_full_to_minimal_redeploys(self, edge_inference_manager_returning):
        """A live full-image deployment is torn down and recreated on minimal when minimal_compatible flips True."""
        with mock.patch.object(inference_image, "INFERENCE_IMAGE_MODE", "minimal_if_compatible"):
            db = _make_db(
                {("detA", False): _detector_record("detA", False), ("detA", True): _detector_record("detA", None)}
            )
            from app.core.naming import get_edge_inference_deployment_name

            primary_name = get_edge_inference_deployment_name("detA", is_oodd=False)
            oodd_name = get_edge_inference_deployment_name("detA", is_oodd=True)
            dm = _make_deployment_manager(initial_images={primary_name: FULL, oodd_name: FULL})
            # After the swap, new pods come up with MINIMAL because by that point minimal_compatible has been persisted
            dm._desired_image_for_create = lambda did, oodd: MINIMAL

            eim = edge_inference_manager_returning(new_model=False, minimal_compatible=True)
            update_models._check_new_models_and_inference_deployments(
                detector_id="detA", edge_inference_manager=eim, deployment_manager=dm, db_manager=db
            )

            assert dm._state.get(primary_name) == MINIMAL
            assert oodd_name not in dm._state  # the OODD pod was torn down by the swap

    def test_crash_mid_swap_recovers(self, edge_inference_manager_returning):
        """If the updater 'crashes' after deletion (simulated by interrupting), the next cycle reaches steady state."""
        with mock.patch.object(inference_image, "INFERENCE_IMAGE_MODE", "minimal_if_compatible"):
            db = _make_db({("detA", False): _detector_record("detA", False)})
            from app.core.naming import get_edge_inference_deployment_name

            primary_name = get_edge_inference_deployment_name("detA", is_oodd=False)
            # Simulate post-crash state: previous cycle deleted the primary but never created the new one.
            dm = _make_deployment_manager(initial_images={})
            dm._desired_image_for_create = lambda did, oodd: MINIMAL

            eim = edge_inference_manager_returning(new_model=False, minimal_compatible=True)
            update_models._check_new_models_and_inference_deployments(
                detector_id="detA", edge_inference_manager=eim, deployment_manager=dm, db_manager=db
            )

            # The next cycle's create-if-missing path brings the primary back up on the right image.
            assert dm._state.get(primary_name) == MINIMAL
