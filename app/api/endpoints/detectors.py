from fastapi import APIRouter, Depends
from starlette.requests import Request
from app.schemas.schemas import DetectorCreate, DetectorCreateResponse, DetectorListResponse


def get_groundlight_instance(request: Request):
    return request.app.state.groundlight


router = APIRouter()


@router.post("/create", response_model=DetectorCreateResponse)
async def create_detector(props: DetectorCreate, gl: Depends = Depends(get_groundlight_instance)):
    detector = gl.create_detector(
        name=props.name,
        query=props.query,
        confidence_threshold=props.confidence_threshold if "confidence_threshold" in props else None,
    )

    return DetectorCreateResponse(result=f"Detector with ID {detector.id} created. ")


@router.get("/list", response_model=DetectorCreateResponse)
async def list_detectors(gl: Depends = Depends(get_groundlight_instance)):
    detectors = gl.list_detectors()

    return DetectorListResponse(
        count=detectors.count,
        detector_names=[detector.name for detector in detectors.results] if detectors.results is not None else None,
    )

