from datetime import datetime

from pydantic import model_validator
from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class InferenceDeployment(SQLModel, table=True):
    """Pydantic + SQLAlchemy model that represents an inference deployment in the `inference_deployments` table."""

    __tablename__ = "inference_deployments"
    detector_id: str = Field(primary_key=True, unique=True, nullable=False, max_length=44)
    api_token: str = Field(nullable=False, max_length=66)
    deployment_created: bool = Field(default=False, nullable=False)
    deployment_name: str | None = Field(default=None, nullable=True, max_length=100)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime | None = Field(
        default_factory=datetime.utcnow, nullable=False, sa_column_kwargs={"onupdate": datetime.utcnow}
    )

    @model_validator(mode="after")
    def check_deployment_name(self):
        if self.deployment_created and self.deployment_name is None:
            raise ValueError("Deployment name must be provided if deployment is marked as created.")
        return self


class ImageQueryEdge(SQLModel, table=True):
    """Pydantic + SQLAlchemy model that represents an image query in the `image_queries_edge` table."""

    __tablename__ = "image_queries_edge"
    image_query_id: str = Field(primary_key=True, unique=True, nullable=False, index=True)
    image_query: dict = Field(sa_column=Column(JSON))
