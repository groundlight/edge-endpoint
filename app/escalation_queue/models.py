from typing import Any

from pydantic import BaseModel


class SubmitImageQueryParams(BaseModel):
    """The parameters of submitting an image query that need to be written to the escalation queue."""

    patience_time: float | None
    confidence_threshold: float | None
    human_review: str | None
    metadata: dict[str, Any] | None
    image_query_id: str


class EscalationInfo(BaseModel):
    """The information about an escalation that needs to be written to the escalation queue."""

    timestamp: str
    detector_id: str
    image_path_str: str
    submit_iq_params: SubmitImageQueryParams
