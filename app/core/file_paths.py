DEFAULT_EDGE_CONFIG_PATH = "/etc/groundlight/edge-config/edge-config.yaml"
INFERENCE_DEPLOYMENT_TEMPLATE_PATH = "/etc/groundlight/inference-deployment/inference_deployment_template.yaml"

# A file with the namespace to be operating within
# TODO: this should just be an environment variable
KUBERNETES_NAMESPACE_PATH = "/etc/groundlight/kubernetes-namespace/namespace"

# Runtime config written by PUT /edge-config. Takes priority over env var / ConfigMap on load.
ACTIVE_EDGE_CONFIG_PATH = "/opt/groundlight/edge/sqlite/active-edge-config.json"

# Snapshot of the helm-provided config at the time set_edge_config was called.
# Used on startup to detect whether helm was upgraded (invalidating the PVC override).
HELM_CONFIG_SNAPSHOT_PATH = "/opt/groundlight/edge/sqlite/helm-config-snapshot.json"

# Path to the database file.
# This must also match the path used in the PersistentVolumeClaim definition for the database.
DATABASE_FILEPATH = "/opt/groundlight/edge/sqlite/sqlite.db"

# Path to the model repository.
MODEL_REPOSITORY_PATH = "/opt/groundlight/edge/serving/model-repo"

# Path to the database log file. This will contain all SQL queries executed by the ORM.
DATABASE_ORM_LOG_FILE = "sqlalchemy.log"
DATABASE_ORM_LOG_FILE_SIZE = 10_000_000  # 10 MB
