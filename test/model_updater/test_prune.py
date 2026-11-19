"""The model updater deletes inference pods for detectors that are no longer in the active edge config."""

import logging
from unittest.mock import MagicMock, patch

import pytest
from groundlight.edge import DEFAULT, EdgeEndpointConfig
from kubernetes.client import (
    V1Deployment,
    V1DeploymentSpec,
    V1LabelSelector,
    V1ObjectMeta,
    V1PodTemplateSpec,
    V1Service,
    V1ServiceSpec,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import DatabaseManager
from app.core.edge_config_manager import EdgeConfigManager, apply_detector_changes, reconcile_config
from app.core.kubernetes_management import DETECTOR_ID_ANNOTATION
from app.core.naming import (
    get_edge_inference_deployment_name,
    get_edge_inference_model_name,
    get_edge_inference_service_name,
)
from app.model_updater import prune, update_models
from app.model_updater.prune import (
    find_orphans,
    prune_unconfigured_inference_resources,
    wait_for_startup_reconciliation,
)

DET_A = "det_AAAAAAAAAAAAAAAAAAAAAAAAAAA"
DET_B = "det_BBBBBBBBBBBBBBBBBBBBBBBBBBB"
DET_C = "det_CCCCCCCCCCCCCCCCCCCCCCCCCCC"


def _instance(detector_id: str, is_oodd: bool) -> str:
    return f"instance-{get_edge_inference_model_name(detector_id, is_oodd).replace('/', '-')}"


def _deployment(detector_id: str, is_oodd: bool = False, annotate: bool = True) -> V1Deployment:
    """An inference Deployment as the model updater creates it."""
    selector = {"app": "inference-server", "instance": _instance(detector_id, is_oodd)}
    annotations = {DETECTOR_ID_ANNOTATION: detector_id} if annotate else None
    return V1Deployment(
        metadata=V1ObjectMeta(name=get_edge_inference_deployment_name(detector_id, is_oodd)),
        spec=V1DeploymentSpec(
            selector=V1LabelSelector(match_labels=selector),
            template=V1PodTemplateSpec(metadata=V1ObjectMeta(labels=selector, annotations=annotations)),
        ),
    )


def _service(detector_id: str, is_oodd: bool = False) -> V1Service:
    selector = {"app": "inference-server", "instance": _instance(detector_id, is_oodd)}
    return V1Service(
        metadata=V1ObjectMeta(name=get_edge_inference_service_name(detector_id, is_oodd)),
        spec=V1ServiceSpec(selector=selector),
    )


def _names(resources) -> set[str]:
    return {r.metadata.name for r in resources}


def _config(*detector_ids: str) -> EdgeEndpointConfig:
    config = EdgeEndpointConfig()
    for detector_id in detector_ids:
        config.add_detector(detector_id, DEFAULT)
    return config


class TestFindOrphans:
    def test_keeps_configured_detectors_and_flags_the_rest(self):
        deployments = [_deployment(d, is_oodd) for d in (DET_A, DET_B) for is_oodd in (False, True)]
        services = [_service(d, is_oodd) for d in (DET_A, DET_B) for is_oodd in (False, True)]

        orphan_deployments, orphan_services = find_orphans(deployments, services, {DET_A}, True)

        assert _names(orphan_deployments) == {
            get_edge_inference_deployment_name(DET_B),
            get_edge_inference_deployment_name(DET_B, is_oodd=True),
        }
        assert _names(orphan_services) == {
            get_edge_inference_service_name(DET_B),
            get_edge_inference_service_name(DET_B, is_oodd=True),
        }

    def test_matches_detector_ids_regardless_of_case(self):
        """Resource names lowercase the detector ID."""
        orphan_deployments, orphan_services = find_orphans(
            [_deployment("det_abc")], [_service("det_abc")], {"det_AbC"}, True
        )
        assert orphan_deployments == [] and orphan_services == []

    def test_oodd_resources_are_wanted_only_with_separate_oodd_inference(self):
        deployments = [_deployment(DET_A), _deployment(DET_A, is_oodd=True)]
        services = [_service(DET_A), _service(DET_A, is_oodd=True)]

        assert find_orphans(deployments, services, {DET_A}, True) == ([], [])

        orphan_deployments, orphan_services = find_orphans(deployments, services, {DET_A}, False)
        assert _names(orphan_deployments) == {get_edge_inference_deployment_name(DET_A, is_oodd=True)}
        assert _names(orphan_services) == {get_edge_inference_service_name(DET_A, is_oodd=True)}

    def test_flags_a_service_whose_deployment_is_already_gone(self):
        orphan_deployments, orphan_services = find_orphans([], [_service(DET_B)], {DET_A}, True)
        assert orphan_deployments == []
        assert _names(orphan_services) == {get_edge_inference_service_name(DET_B)}

    def test_no_desired_detectors_flags_everything(self):
        orphan_deployments, orphan_services = find_orphans([_deployment(DET_A)], [_service(DET_A)], set(), True)
        assert len(orphan_deployments) == 1 and len(orphan_services) == 1


@pytest.fixture
def active_config(tmp_path, monkeypatch):
    """Point the active edge config at a temp file; returns its path."""
    path = tmp_path / "active-edge-config.yaml"
    monkeypatch.setattr("app.core.edge_config_manager.ACTIVE_EDGE_CONFIG_PATH", str(path))
    return path


@pytest.fixture(autouse=True)
def no_sleep():
    with patch.object(prune.time, "sleep") as sleep:
        yield sleep


def _deployment_manager(deployments=(), services=()) -> MagicMock:
    """A deployment manager whose deleted deployments are gone right away."""
    mgr = MagicMock()
    mgr.namespace = "edge-2"
    mgr.list_inference_deployments.return_value = list(deployments)
    mgr.list_inference_services.return_value = list(services)
    mgr.get_inference_deployment.return_value = None
    mgr.inference_pods_gone.return_value = True
    return mgr


def _db_manager(active_ids=()) -> MagicMock:
    db = MagicMock()
    db.get_active_detector_ids.return_value = set(active_ids)
    return db


def _deleted(mgr: MagicMock) -> set[str]:
    return {
        name for c in mgr.delete_inference_resources.call_args_list for name in c.kwargs.values() if name is not None
    }


def _prune(mgr: MagicMock, db: MagicMock | None = None, separate_oodd_inference: bool = True, timeout_s=180) -> None:
    prune_unconfigured_inference_resources(
        deployment_manager=mgr,
        db_manager=db or _db_manager(),
        separate_oodd_inference=separate_oodd_inference,
        timeout_s=timeout_s,
    )


class TestPruneGates:
    @pytest.mark.parametrize("value", [None, "false", "False", ""])
    def test_does_nothing_unless_configured_detectors_are_required(self, monkeypatch, active_config, value):
        """Unlisted detectors get pods on demand then, and their DB records don't survive a restart."""
        if value is None:
            monkeypatch.delenv("REQUIRE_CONFIGURED_DETECTORS", raising=False)
        else:
            monkeypatch.setenv("REQUIRE_CONFIGURED_DETECTORS", value)
        EdgeConfigManager.save(_config())
        mgr = _deployment_manager([_deployment(DET_B)], [_service(DET_B)])

        _prune(mgr)

        mgr.list_inference_deployments.assert_not_called()
        mgr.list_inference_services.assert_not_called()
        mgr.delete_inference_resources.assert_not_called()

    @pytest.mark.parametrize("content", [None, "", "  \n", "{}", "detectors: [unclosed\n"])
    def test_skips_with_a_warning_when_the_active_config_cant_be_read(
        self, monkeypatch, active_config, caplog, content
    ):
        """Reading these as an empty config would delete every inference pod."""
        monkeypatch.setenv("REQUIRE_CONFIGURED_DETECTORS", "true")
        if content is not None:
            active_config.write_text(content)
        mgr = _deployment_manager([_deployment(DET_B)], [_service(DET_B)])

        with caplog.at_level(logging.WARNING, logger=prune.__name__):
            _prune(mgr)

        mgr.delete_inference_resources.assert_not_called()
        assert any("Not pruning" in r.message for r in caplog.records if r.levelno == logging.WARNING)


@pytest.fixture
def prune_enabled(monkeypatch, active_config):
    monkeypatch.setenv("REQUIRE_CONFIGURED_DETECTORS", "true")
    return active_config


class TestPrune:
    def test_deletes_unconfigured_detectors_and_keeps_configured_ones(self, prune_enabled):
        EdgeConfigManager.save(_config(DET_A))
        mgr = _deployment_manager(
            [_deployment(d, is_oodd) for d in (DET_A, DET_B) for is_oodd in (False, True)],
            [_service(d, is_oodd) for d in (DET_A, DET_B) for is_oodd in (False, True)],
        )

        _prune(mgr)

        assert _deleted(mgr) == {
            get_edge_inference_deployment_name(DET_B),
            get_edge_inference_deployment_name(DET_B, is_oodd=True),
            get_edge_inference_service_name(DET_B),
            get_edge_inference_service_name(DET_B, is_oodd=True),
        }

    def test_keeps_detectors_that_are_only_in_the_db(self, prune_enabled):
        EdgeConfigManager.save(_config(DET_A))
        mgr = _deployment_manager([_deployment(DET_A), _deployment(DET_C)], [_service(DET_A), _service(DET_C)])

        _prune(mgr, db=_db_manager({DET_C}))

        mgr.delete_inference_resources.assert_not_called()

    def test_a_config_with_no_detectors_deletes_every_inference_pod(self, prune_enabled):
        """Only configured detectors get pods, and none are configured."""
        EdgeConfigManager.save(_config())
        mgr = _deployment_manager([_deployment(DET_A)], [_service(DET_A)])

        _prune(mgr)

        assert _deleted(mgr) == {get_edge_inference_deployment_name(DET_A), get_edge_inference_service_name(DET_A)}

    def test_logs_each_deletion_with_its_namespace_and_detector(self, prune_enabled, caplog):
        EdgeConfigManager.save(_config())
        mgr = _deployment_manager([_deployment(DET_A), _deployment(DET_B, annotate=False)])

        with caplog.at_level(logging.INFO, logger=prune.__name__):
            _prune(mgr)

        messages = [r.message for r in caplog.records]
        assert any(get_edge_inference_deployment_name(DET_A) in m and "edge-2" in m and DET_A in m for m in messages)
        assert any(get_edge_inference_deployment_name(DET_B) in m and "detector unknown" in m for m in messages)

    def test_waits_for_pruned_pods_to_exit(self, prune_enabled, no_sleep):
        EdgeConfigManager.save(_config())
        mgr = _deployment_manager([_deployment(DET_B, is_oodd=True)])
        polls_while_running = 2
        mgr.inference_pods_gone.side_effect = [False] * polls_while_running + [True]

        _prune(mgr)

        assert no_sleep.call_count == polls_while_running
        # The instance label keeps the detector ID's case, which the deployment name has lost.
        assert {c.args[0] for c in mgr.inference_pods_gone.call_args_list} == {_instance(DET_B, is_oodd=True)}

    def test_gives_up_waiting_with_an_error(self, prune_enabled, caplog):
        EdgeConfigManager.save(_config())
        mgr = _deployment_manager([_deployment(DET_B)])
        mgr.inference_pods_gone.return_value = False

        with caplog.at_level(logging.ERROR, logger=prune.__name__):
            _prune(mgr, timeout_s=0)

        assert any("Timed out" in r.message for r in caplog.records if r.levelno == logging.ERROR)

    def test_nothing_to_prune_makes_no_deletes(self, prune_enabled):
        EdgeConfigManager.save(_config(DET_A))
        mgr = _deployment_manager([_deployment(DET_A)], [_service(DET_A)])

        _prune(mgr)

        mgr.delete_inference_resources.assert_not_called()
        mgr.inference_pods_gone.assert_not_called()


@pytest.fixture
def real_db(tmp_path):
    """The real DatabaseManager on a SQLite file, which outlives the pod like the one on the PVC."""
    db = DatabaseManager(verbose=False)
    db._engine = create_engine(f"sqlite:///{tmp_path / 'sqlite.db'}")
    db.session_maker = sessionmaker(bind=db._engine)
    db.create_tables()
    yield db
    db.shutdown()


def _edge_endpoint_startup(db: DatabaseManager, *detector_ids: str):
    """Return a callable that runs the edge-endpoint's startup DB reset and reconcile, once."""
    started = []

    def startup(*_args, **_kwargs) -> None:
        if not started:
            started.append(True)
            db.reset_database()
            reconcile_config(_config(*detector_ids), db)

    return startup


class TestWaitForStartupReconciliation:
    def test_returns_at_once_when_the_db_matches_the_config(self, prune_enabled, real_db, no_sleep):
        reconcile_config(_config(DET_A), real_db)

        wait_for_startup_reconciliation(real_db, timeout_s=300)

        no_sleep.assert_not_called()

    def test_waits_for_the_edge_endpoint_to_reset_and_reconcile_a_stale_db(self, prune_enabled, real_db, no_sleep):
        apply_detector_changes(removed=set(), added={DET_B}, db_manager=real_db)
        EdgeConfigManager.save(_config(DET_A))
        no_sleep.side_effect = _edge_endpoint_startup(real_db, DET_A)

        wait_for_startup_reconciliation(real_db, timeout_s=300)

        assert no_sleep.call_count == 1
        assert real_db.get_active_detector_ids() == {DET_A}

    def test_keeps_waiting_while_the_db_is_being_reset(self, prune_enabled, no_sleep):
        EdgeConfigManager.save(_config(DET_A))
        db = MagicMock()
        db.get_active_detector_ids.side_effect = [RuntimeError("no such table: inference_deployments"), {DET_A}]

        wait_for_startup_reconciliation(db, timeout_s=300)

        assert no_sleep.call_count == 1

    def test_gives_up_with_a_warning_after_the_timeout(self, prune_enabled, caplog):
        EdgeConfigManager.save(_config(DET_A))

        with caplog.at_level(logging.WARNING, logger=prune.__name__):
            wait_for_startup_reconciliation(_db_manager({DET_B}), timeout_s=0)

        assert any("did not reconcile" in r.message for r in caplog.records if r.levelno == logging.WARNING)

    def test_does_nothing_when_pruning_is_disabled(self, monkeypatch, active_config):
        monkeypatch.setenv("REQUIRE_CONFIGURED_DETECTORS", "false")
        db = _db_manager({DET_B})

        wait_for_startup_reconciliation(db, timeout_s=300)

        db.get_active_detector_ids.assert_not_called()


class _StopLoopError(Exception):
    pass


def _run_one_iteration(mgr: MagicMock, db, sleep=None) -> None:
    """Run manage_update_models until it starts waiting for the next cycle."""
    edge_inference_manager = MagicMock()
    edge_inference_manager.update_models_if_available.return_value = False
    with (
        patch.dict("os.environ", {"DEPLOY_DETECTOR_LEVEL_INFERENCE": "1"}),
        patch.object(update_models, "_wait_for_next_cycle", side_effect=_StopLoopError),
        patch.object(update_models.time, "sleep", side_effect=sleep),
        pytest.raises(_StopLoopError),
    ):
        update_models.manage_update_models(
            edge_inference_manager=edge_inference_manager,
            deployment_manager=mgr,
            db_manager=db,
            separate_oodd_inference=True,
        )


def _loop_db_manager(configured: str, pending_deletions=()) -> MagicMock:
    db = _db_manager({configured})
    db.get_pending_deletions.return_value = list(pending_deletions)
    record = MagicMock(detector_id=configured)
    db.get_inference_deployment_records.return_value = [record]
    return db


class TestModelUpdaterLoop:
    def test_prunes_before_creating_any_deployment(self, prune_enabled):
        EdgeConfigManager.save(_config(DET_A))
        mgr = _deployment_manager([_deployment(DET_B)], [_service(DET_B)])
        mgr.is_inference_deployment_rollout_complete.return_value = False

        _run_one_iteration(mgr, _loop_db_manager(DET_A))

        names = [c[0] for c in mgr.mock_calls]
        assert "delete_inference_resources" in names and "create_inference_deployment" in names
        last_delete = max(i for i, n in enumerate(names) if n == "delete_inference_resources")
        first_create = names.index("create_inference_deployment")
        assert last_delete < first_create
        created = {c.kwargs["detector_id"] for c in mgr.create_inference_deployment.call_args_list}
        assert created == {DET_A}

    def test_a_detector_removed_before_a_restart_is_pruned_before_its_replacement_is_created(
        self, prune_enabled, real_db
    ):
        """After a Helm config change replaces B with A, the DB still lists B until the edge-endpoint starts.

        The edge-endpoint's startup lands at the first point the updater could reach it: while the updater
        waits, or between the pruner's DB read and the model update's DB read.
        """
        apply_detector_changes(removed=set(), added={DET_B}, db_manager=real_db)
        EdgeConfigManager.save(_config(DET_A))
        deployments = {d.metadata.name: d for d in (_deployment(DET_B), _deployment(DET_B, is_oodd=True))}
        services = {s.metadata.name: s for s in (_service(DET_B), _service(DET_B, is_oodd=True))}
        edge_endpoint_startup = _edge_endpoint_startup(real_db, DET_A)

        def list_services() -> list[V1Service]:
            edge_endpoint_startup()
            return list(services.values())

        def delete(deployment_name=None, service_name=None) -> None:
            deployments.pop(deployment_name, None)
            services.pop(service_name, None)

        mgr = _deployment_manager()
        mgr.list_inference_deployments.side_effect = lambda: list(deployments.values())
        mgr.list_inference_services.side_effect = list_services
        mgr.get_inference_deployment.side_effect = lambda deployment_name: deployments.get(deployment_name)
        mgr.delete_inference_resources.side_effect = delete
        mgr.is_inference_deployment_rollout_complete.return_value = False

        _run_one_iteration(mgr, real_db, sleep=edge_endpoint_startup)

        assert _deleted(mgr) == {
            get_edge_inference_deployment_name(DET_B),
            get_edge_inference_deployment_name(DET_B, is_oodd=True),
            get_edge_inference_service_name(DET_B),
            get_edge_inference_service_name(DET_B, is_oodd=True),
        }
        assert [c.kwargs for c in mgr.create_inference_deployment.call_args_list] == [
            {"detector_id": DET_A},
            {"detector_id": DET_A, "is_oodd": True},
        ]
        names = [c[0] for c in mgr.mock_calls]
        last_delete = max(i for i, n in enumerate(names) if n == "delete_inference_resources")
        assert last_delete < names.index("create_inference_deployment")

    def test_pending_deletions_are_still_processed(self, monkeypatch, active_config):
        monkeypatch.setenv("REQUIRE_CONFIGURED_DETECTORS", "false")
        mgr = _deployment_manager()
        mgr.is_inference_deployment_fully_deleted.return_value = True
        mgr.is_inference_deployment_rollout_complete.return_value = False
        db = _loop_db_manager(DET_A, pending_deletions=[DET_B])

        _run_one_iteration(mgr, db)

        assert [c.args for c in mgr.delete_inference_deployment.call_args_list] == [(DET_B,), (DET_B,)]
        assert [c.kwargs for c in mgr.delete_inference_deployment.call_args_list] == [{}, {"is_oodd": True}]
        db.delete_inference_deployment_records.assert_called_once_with(DET_B)

    def test_a_pruning_failure_does_not_stop_model_updates(self, prune_enabled, caplog):
        EdgeConfigManager.save(_config(DET_A))
        mgr = _deployment_manager()
        mgr.list_inference_deployments.side_effect = RuntimeError("apiserver unavailable")
        mgr.is_inference_deployment_rollout_complete.return_value = False

        with caplog.at_level(logging.ERROR, logger=update_models.__name__):
            _run_one_iteration(mgr, _loop_db_manager(DET_A))

        assert {c.kwargs["detector_id"] for c in mgr.create_inference_deployment.call_args_list} == {DET_A}
        assert any("Failed to prune" in r.message for r in caplog.records)
