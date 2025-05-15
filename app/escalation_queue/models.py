from typing import Any

from pydantic import BaseModel


class SubmitImageQueryParams(BaseModel):
    patience_time: float | None
    confidence_threshold: float
    human_review: str | None
    metadata: dict[str, Any] | None
    image_query_id: str | None = None


class EscalationInfo(BaseModel):
    timestamp: str
    detector_id: str
    image_path_str: str
    submit_iq_params: SubmitImageQueryParams
