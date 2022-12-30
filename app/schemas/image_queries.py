from pydantic import BaseModel, Field


class ImageQueryCreate(BaseModel):
    detector_id: str = Field(description="Detector ID")


class ImageQueryResponse(BaseModel):
    result: str = Field(description="Image query result")
