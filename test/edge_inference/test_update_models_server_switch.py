"""The model updater moves existing inference deployments to the configured inference server."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.inference_server import InferenceServer
from app.model_updater import update_models

DET = "det_abc"


def _deployment_manager(primary: InferenceServer, oodd: InferenceServer) -> MagicMock:
    """A deployment manager whose existing primary and OODD deployments run the given servers."""
    deployments = {"primary": MagicMock(name="primary"), "oodd": MagicMock(name="oodd")}
    servers = {id(deployments["primary"]): primary, id(deployments["oodd"]): oodd}
    mgr = MagicMock()
    mgr.get_inference_deployment.side_effect = lambda deployment_name: deployments[
        "oodd" if "oodd" in deployment_name else "primary"
    ]
    mgr.deployment_inference_server.side_effect = lambda deployment: servers[id(deployment)]
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


def test_moves_deployments_still_on_the_old_server(monkeypatch: pytest.MonkeyPatch, delete_old_model_versions):
    monkeypatch.setenv("INFERENCE_SERVER", "triton")
    mgr = _deployment_manager(InferenceServer.FASTAPI, InferenceServer.FASTAPI)
    # Rollout not started for either deployment, then complete for both, then the final readiness check.
    mgr.is_inference_deployment_rollout_complete.side_effect = [False, False, True, True, True, True]

    _check(mgr, new_model=False)

    assert [c.kwargs for c in mgr.switch_inference_server.call_args_list] == [
        {"detector_id": DET},
        {"detector_id": DET, "is_oodd": True},
    ]
    mgr.update_inference_deployment.assert_not_called()
    delete_old_model_versions.assert_not_called()


def test_moves_both_deployments_when_only_one_is_on_the_old_server(monkeypatch: pytest.MonkeyPatch):
    """Both are switched, which restarts both, so the rollout wait, which watches both, sees both roll."""
    monkeypatch.setenv("INFERENCE_SERVER", "fastapi")
    mgr = _deployment_manager(InferenceServer.FASTAPI, InferenceServer.TRITON)
    mgr.is_inference_deployment_rollout_complete.side_effect = [False, False, True, True, True, True]

    _check(mgr, new_model=False)

    assert mgr.switch_inference_server.call_count == 2


def test_leaves_deployments_on_the_configured_server_alone(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("INFERENCE_SERVER", "triton")
    mgr = _deployment_manager(InferenceServer.TRITON, InferenceServer.TRITON)
    mgr.is_inference_deployment_rollout_complete.return_value = True

    _check(mgr, new_model=False)

    mgr.switch_inference_server.assert_not_called()
    mgr.update_inference_deployment.assert_not_called()


def test_a_new_model_on_the_configured_server_is_rolled_out_as_before(
    monkeypatch: pytest.MonkeyPatch, delete_old_model_versions
):
    monkeypatch.delenv("INFERENCE_SERVER", raising=False)
    mgr = _deployment_manager(InferenceServer.FASTAPI, InferenceServer.FASTAPI)
    mgr.is_inference_deployment_rollout_complete.side_effect = [False, False, True, True, True, True]

    _check(mgr, new_model=True)

    mgr.switch_inference_server.assert_not_called()
    assert mgr.update_inference_deployment.call_count == 2
    delete_old_model_versions.assert_called_once()
