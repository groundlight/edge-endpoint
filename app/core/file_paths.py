DEFAULT_EDGE_CONFIG_PATH = "/etc/groundlight/edge-config/edge-config.yaml"

# Runtime config written by the POST /edge/configure API. Stored on the shared PVC
# (edge-endpoint-pvc) which is mounted at different paths in different containers.
# We check all known mount points so any container can find it.
_RUNTIME_CONFIG_FILENAME = "runtime-edge-config.yaml"
RUNTIME_EDGE_CONFIG_PATHS = [
    f"/opt/groundlight/edge/sqlite/{_RUNTIME_CONFIG_FILENAME}",
    f"/opt/groundlight/edge/serving/model-repo/{_RUNTIME_CONFIG_FILENAME}",
]
INFERENCE_DEPLOYMENT_TEMPLATE_PATH = "/etc/groundlight/inference-deployment/inference_deployment_template.yaml"

# A file with the namespace to be operating within
# TODO: this should just be an environment variable
KUBERNETES_NAMESPACE_PATH = "/etc/groundlight/kubernetes-namespace/namespace"

# Path to the database file.
# This must also match the path used in the PersistentVolumeClaim definition for the database.
DATABASE_FILEPATH = "/opt/groundlight/edge/sqlite/sqlite.db"

# Path to the model repository.
MODEL_REPOSITORY_PATH = "/opt/groundlight/edge/serving/model-repo"

# Path to the database log file. This will contain all SQL queries executed by the ORM.
DATABASE_ORM_LOG_FILE = "sqlalchemy.log"
DATABASE_ORM_LOG_FILE_SIZE = 10_000_000  # 10 MB
