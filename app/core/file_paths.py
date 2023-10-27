DEFAULT_EDGE_CONFIG_PATH = "/etc/groundlight/edge-config/edge-config.yaml"
INFERENCE_DEPLOYMENT_TEMPLATE_PATH = "/etc/groundlight/inference-deployment/inference_deployment_template.yaml"

# Name of the database container in the edge-endpoint deployment.
# If you change this, you must also change it in the edge-endpoint deployment and vice versa.
DATABASE_CONTAINER_NAME = "sqlite-db"

# Path to the database file mounted into the sqlite-db container.
# This must also match the path used in the PersistentVolumeClaim definition for the database.
DATABASE_FILEPATH = "/var/groundlight/sqlite/sqlite.db"
