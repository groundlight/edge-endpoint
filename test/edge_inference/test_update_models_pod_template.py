"""The model updater moves existing inference deployments to the configured inference server and GPU sharing."""

from unittest.mock import MagicMock, patch

import pytest

from app.model_updater import update_models

DET = "det_abc"


def _deployment_manager(primary_outdated: bool, oodd_outdated: bool) -> MagicMock:
    """A deployment manager whose existing primary and OODD deployments have outdated pod templates or not."""
    deployments = {"primary": MagicMock(name="primary"), "oodd": MagicMock(name="oodd")}
    outdated = {id(deployments["primary"]): primary_outdated, id(deployments["oodd"]): oodd_outdated}
    mgr = MagicMock()
    mgr.get_inference_deployment.side_effect = lambda deployment_name: deployments[
        "oodd" if "oodd" in deployment_name else "primary"
    ]
    mgr.pod_template_is_outdated.side_effect = lambda deployment: outdated[id(deployment)]
    return mgr


def _check(mgr: MagicMock, new_model: bool) -> None:
    edge_inference_manager = MagicMock()
    edge_inference_manager.update_models_if_available.return_value = new_model
    with patch.object(update_models.time, "sleep"):
        update_models._check_new_models_and_inference_deployments(
            detector_id=DET,
            edge_inference_manager=edge_inference_manager,
            deployment_manager=mgr,
            db_manager=MagicMock(),
            separate_oodd_inference=True,
        )


@pytest.fixture
def delete_old_model_versions():
    with patch.object(update_models, "delete_old_model_versions") as delete:
        yield delete


def test_moves_deployments_with_outdated_pod_templates(delete_old_model_versions):
    mgr = _deployment_manager(primary_outdated=True, oodd_outdated=True)
    # Rollout not started for either deployment, then complete for both, then the final readiness check.
    mgr.is_inference_deployment_rollout_complete.side_effect = [False, False, True, True, True, True]

    _check(mgr, new_model=False)

    assert [c.kwargs for c in mgr.rerender_inference_deployment.call_args_list] == [
        {"detector_id": DET},
        {"detector_id": DET, "is_oodd": True},
    ]
    mgr.update_inference_deployment.assert_not_called()
    delete_old_model_versions.assert_not_called()


def test_moves_both_deployments_when_only_one_is_outdated():
    """Both are re-rendered, which restarts both, so the rollout wait, which watches both, sees both roll."""
    mgr = _deployment_manager(primary_outdated=False, oodd_outdated=True)
    mgr.is_inference_deployment_rollout_complete.side_effect = [False, False, True, True, True, True]

    _check(mgr, new_model=False)

    assert mgr.rerender_inference_deployment.call_count == 2


def test_leaves_up_to_date_deployments_alone():
    mgr = _deployment_manager(primary_outdated=False, oodd_outdated=False)
    mgr.is_inference_deployment_rollout_complete.return_value = True

    _check(mgr, new_model=False)

    mgr.rerender_inference_deployment.assert_not_called()
    mgr.update_inference_deployment.assert_not_called()


def test_a_new_model_for_an_up_to_date_deployment_is_rolled_out_as_before(delete_old_model_versions):
    mgr = _deployment_manager(primary_outdated=False, oodd_outdated=False)
    mgr.is_inference_deployment_rollout_complete.side_effect = [False, False, True, True, True, True]

    _check(mgr, new_model=True)

    mgr.rerender_inference_deployment.assert_not_called()
    assert mgr.update_inference_deployment.call_count == 2
    delete_old_model_versions.assert_called_once()
