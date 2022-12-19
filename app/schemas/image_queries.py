from pydantic import BaseModel, Field


class PostImageQueryProps(BaseModel):
    detector_id: str = Field(description="Detector ID")


class PostImageQueryResponse(BaseModel):
    response: str = Field(description="Response")
