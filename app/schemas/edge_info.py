from pydantic import BaseModel, Field


class EdgeInfo(BaseModel):
    upstream_endpoint: str = Field(
        description="Origin of the Groundlight cloud this Edge Endpoint escalates and forwards requests to.",
        examples=["https://api.groundlight.ai"],
    )
