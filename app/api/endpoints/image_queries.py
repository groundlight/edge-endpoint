from fastapi import APIRouter

from app.schemas.image_queries import ImageQueryCreate, ImageQueryResponse

router = APIRouter()


@router.post("", response_model=ImageQueryResponse)
async def post_image_query(props: ImageQueryCreate):
    """
    Submit an image query to the detector.
    """
    # TODO: Implement near-duplicate detection!

    return ImageQueryResponse(result=f"Response for {props.detector_id}!")
