from typing import Any

from pydantic import BaseModel

from app.core.utils import generate_iq_id


class SubmitImageQueryParams(BaseModel):
    patience_time: float | None
    confidence_threshold: float
    human_review: str | None
    metadata: dict[str, Any] | None
    image_query_id: str = (
        generate_iq_id()
    )  # We always escalate with a specified IQ ID so that we can know if we've already escalated a queued escalation


class EscalationInfo(BaseModel):
    timestamp: str
    detector_id: str
    image_path_str: str
    submit_iq_params: SubmitImageQueryParams
