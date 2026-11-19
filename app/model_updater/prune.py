"""Delete inference Deployments and Services for detectors that are not in the active edge config."""

import logging
import os
import time
from collections.abc import Iterable

from kubernetes.client import V1Deployment, V1Service

from app.core.database import DatabaseManager
from app.core.edge_config_manager import EdgeConfigManager, require_configured_detectors
from app.core.kubernetes_management import DETECTOR_ID_ANNOTATION, InferenceDeploymentManager
from app.core.naming import get_edge_inference_deployment_name, get_edge_inference_service_name

logger = logging.getLogger(__name__)

PRUNE_POLL_INTERVAL_S = 5.0
RECONCILE_POLL_INTERVAL_S = 2.0


def pruning_enabled() -> bool:
    """Whether to prune: only while image queries are limited to configured detectors.

    With requireConfiguredDetectors=false, an unlisted detector gets a pod on demand, so a pod for a
    detector missing from the config may still be wanted. Unset means don't prune, because a chart that
    doesn't pass REQUIRE_CONFIGURED_DETECTORS to the model updater can't tell the two apart.
    """
    return "REQUIRE_CONFIGURED_DETECTORS" in os.environ and require_configured_detectors()


def wait_for_startup_reconciliation(db_manager: DatabaseManager, timeout_s: float) -> None:
    """Wait until the DB's active detectors are exactly those in the active edge config.

    The DB outlives the pod, and the edge-endpoint resets and reconciles it only once it has started.
    Until then it can still list detectors removed from the config, which pruning would keep while the
    model updater creates pods for the new ones. Both would then hold RAM/VRAM until the next pass, and a
    device that can't fit both can fail to load the new pods or evict other pods. Does nothing unless
    pruning_enabled(). Gives up with a warning after timeout_s.
    """
    if not pruning_enabled():
        return
    start = time.monotonic()
    waiting_logged = False
    while True:
        try:
            configured = {d.detector_id for d in EdgeConfigManager.load_strict().detectors}
            active = db_manager.get_active_detector_ids()
            if active == configured:
                if waiting_logged:
                    logger.info(f"Edge endpoint reconciled the DB after {time.monotonic() - start:.1f}s")
                return
            state = f"DB has {sorted(active)}, active edge config has {sorted(configured)}"
        # The DB's tables are dropped and recreated during the reset, and the config may not be written yet.
        except Exception as e:
            state = f"{type(e).__name__}: {e}"
        if not waiting_logged:
            logger.info(f"Waiting for the edge endpoint to reconcile the DB with the active edge config ({state})")
            waiting_logged = True
        if time.monotonic() - start >= timeout_s:
            logger.warning(
                f"Edge endpoint did not reconcile the DB with the active edge config within {timeout_s}s "
                f"({state}); continuing"
            )
            return
        time.sleep(RECONCILE_POLL_INTERVAL_S)


def find_orphans(
    deployments: Iterable[V1Deployment],
    services: Iterable[V1Service],
    desired_detector_ids: set[str],
    separate_oodd_inference: bool,
) -> tuple[list[V1Deployment], list[V1Service]]:
    """Return the inference Deployments and Services that none of the desired detectors would have.

    Expects resources from InferenceDeploymentManager.list_inference_deployments/services. Compares
    names, because a resource name lowercases the detector ID and can't be mapped back to it. OODD
    resources are wanted only when OODD inference runs in its own pods.
    """
    kinds = [False, True] if separate_oodd_inference else [False]
    wanted_deployments = {
        get_edge_inference_deployment_name(detector_id, is_oodd)
        for detector_id in desired_detector_ids
        for is_oodd in kinds
    }
    wanted_services = {
        get_edge_inference_service_name(detector_id, is_oodd)
        for detector_id in desired_detector_ids
        for is_oodd in kinds
    }
    return (
        [d for d in deployments if d.metadata.name not in wanted_deployments],
        [s for s in services if s.metadata.name not in wanted_services],
    )


def prune_unconfigured_inference_resources(
    deployment_manager: InferenceDeploymentManager,
    db_manager: DatabaseManager,
    separate_oodd_inference: bool,
    timeout_s: float,
) -> None:
    """Delete inference Deployments and Services in the manager's namespace that no configured detector needs.

    Does nothing unless pruning_enabled(), and skips with a warning when the active config is missing,
    empty, or invalid. Detectors with active DB records are kept too. Waits up to timeout_s for the
    deleted pods to exit, so their RAM/VRAM is free before any new pods are created.
    """
    if not pruning_enabled():
        return
    try:
        config = EdgeConfigManager.load_strict()
    except (OSError, ValueError) as e:
        logger.warning(f"Not pruning inference deployments, because the active edge config can't be read: {e}")
        return

    # The model updater creates pods for every active DB record, so pruning one the config lacks (as when the
    # edge-endpoint hasn't reconciled the DB yet) would only get its pods recreated on every pass.
    desired_detector_ids = {d.detector_id for d in config.detectors} | db_manager.get_active_detector_ids()
    orphan_deployments, orphan_services = find_orphans(
        deployments=deployment_manager.list_inference_deployments(),
        services=deployment_manager.list_inference_services(),
        desired_detector_ids=desired_detector_ids,
        separate_oodd_inference=separate_oodd_inference,
    )
    if not orphan_deployments and not orphan_services:
        return

    namespace = deployment_manager.namespace
    # The `instance` label keeps the detector ID's original case, which the deployment name has lost.
    pods_to_wait_for: dict[str, str | None] = {}
    for deployment in orphan_deployments:
        name = deployment.metadata.name
        template_metadata = deployment.spec.template.metadata
        annotations = (template_metadata.annotations if template_metadata else None) or {}
        detector_id = annotations.get(DETECTOR_ID_ANNOTATION, "unknown")
        logger.info(
            f"Pruning inference deployment {name} in namespace {namespace} (detector {detector_id}): "
            "its detector is not in the active edge config"
        )
        pods_to_wait_for[name] = (deployment.spec.selector.match_labels or {}).get("instance")
        deployment_manager.delete_inference_resources(deployment_name=name)
    for service in orphan_services:
        logger.info(
            f"Pruning inference service {service.metadata.name} in namespace {namespace}: "
            "its detector is not in the active edge config"
        )
        deployment_manager.delete_inference_resources(service_name=service.metadata.name)

    deadline = time.monotonic() + timeout_s
    while True:
        pods_to_wait_for = {
            name: instance
            for name, instance in pods_to_wait_for.items()
            if deployment_manager.get_inference_deployment(name) is not None
            or (instance is not None and not deployment_manager.inference_pods_gone(instance))
        }
        if not pods_to_wait_for:
            logger.info(
                f"Pruned {len(orphan_deployments)} inference deployment(s) and {len(orphan_services)} service(s) "
                f"in namespace {namespace}"
            )
            return
        if time.monotonic() >= deadline:
            logger.error(
                f"Timed out after {timeout_s}s waiting for pruned inference pods to exit in namespace {namespace}: "
                f"{sorted(pods_to_wait_for)}"
            )
            return
        time.sleep(PRUNE_POLL_INTERVAL_S)
