import datetime

import sqlalchemy as sa
from pydantic import SecretStr
from sqlalchemy import JSON, Boolean, Column, DateTime, String, create_engine, inspect
from sqlalchemy.orm import declarative_base
from sqlmodel import Field, SQLModel

# Create an engine for your database
engine = create_engine("sqlite:///:memory:")  # Use an in-memory SQLite database

# Create an inspector
inspector = inspect(engine)

Base = declarative_base()


class SecretStrType(sa.types.TypeDecorator):
    impl = sa.types.VARCHAR  # Default to VARCHAR, but without a fixed length

    def __init__(self, length=None, **kwargs):
        self.length = length
        super().__init__(**kwargs)

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(sa.types.VARCHAR(self.length))

    def process_bind_param(self, value: SecretStr, dialect):
        return value.get_secret_value()

    def process_result_value(self, value: str, dialect):
        return SecretStr(value)


class InferenceDeployment(SQLModel, table=True):
    """Pydantic + SQLAlchemy model that represents an inference deployment in the `inference_deployments` table."""

    __tablename__ = "inference_deployments"
    detector_id: str = Field(primary_key=True, unique=True, nullable=False, max_length=44)
    api_token: SecretStr = Field(nullable=False, sa_type=SecretStrType(length=66))
    deployment_created: bool = Field(default=False, nullable=False)
    deployment_name: str = Field(nullable=True, max_length=100)
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    updated_at: datetime.datetime | None = Field(
        default_factory=lambda: datetime.datetime.utcnow,
        nullable=False,
        sa_column_kwargs={"onupdate": datetime.datetime.utcnow},
    )


class ImageQueryEdge(SQLModel, table=True):
    """Pydantic + SQLAlchemy model that represents an image query in the `image_queries_edge` table."""

    __tablename__ = "image_queries_edge"
    image_query_id: str = Field(primary_key=True, unique=True, nullable=False, index=True)
    image_query: dict = Field(sa_column=Column(JSON))


class InferenceDeploymentOld(Base):
    """
    Schema for the the `inference_deployments` database table.
    This is used by both the `edge-endpoint` and `inference-model-updater` containers.

    - The `edge-endpoint` container uses this table to add new detector ID's for which
    kubernetes deployments need to be created.
    - The `inference-model-updater` container uses it to create inference deployments for
    new detectors.

    """

    __tablename__ = "inference_deployments_old"
    detector_id = Column(String(44), primary_key=True, unique=True, nullable=False, comment="Detector ID")

    api_token = Column(String(66), nullable=False, comment="API token")
    deployment_created = Column(
        Boolean,
        default=False,
        nullable=False,
        comment=("Indicates whether the given detector already has an inference deployment in the kubernetes cluster."),
    )
    deployment_name = Column(
        String(100),
        nullable=True,
        comment="Name of the kubernetes deployment for the inference server.",
    )

    created_at = Column(
        DateTime, nullable=True, default=datetime.datetime.utcnow, comment="Timestamp of record creation"
    )
    updated_at = Column(
        DateTime,
        nullable=True,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
        comment="Timestamp of record update",
    )


class ImageQueriesEdgeOld(Base):
    """
    Schema for the `image_queries_edge` database table.
    This table is used  by the `edge-endpoint` container to store image queries created from the
    `POST /image-queries` endpoint on the edge.

    This is necessary because the core Groundlight service does not recognize these image queries.
    Storing them in this table allows us to properly handle `GET /image-queries/{image_query_id}` on the edge.

    """

    __tablename__ = "image_queries_edge_old"
    image_query_id = Column(
        String,
        primary_key=True,
        unique=True,
        nullable=False,
        index=True,
        comment="Image query ID. This is expected to be prefixed with `iqe_`.",
    )
    image_query = Column(JSON, nullable=False, comment="JSON representation of the ImageQuery data model.")


SQLModel.metadata.create_all(engine)
Base.metadata.create_all(engine)


# Function to print table schema
def print_table_schema(table_name):
    print(f"Schema for table '{table_name}':")
    columns = inspector.get_columns(table_name)
    for column in columns:
        print(f"  {column['name']} ({column['type']})")
    print()


# Print schema for each table
print_table_schema(InferenceDeployment.__tablename__)
print_table_schema(ImageQueryEdge.__tablename__)
print_table_schema(InferenceDeploymentOld.__tablename__)
print_table_schema(ImageQueriesEdgeOld.__tablename__)
