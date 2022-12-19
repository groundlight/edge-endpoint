from fastapi import APIRouter

from app.schemas.image_queries import PostImageQueryProps, PostImageQueryResponse

router = APIRouter()


@router.post("", response_model=PostImageQueryResponse)
async def post_image_query(props: PostImageQueryProps):
    """
    Submit an image query to the detector.
    """
    return PostImageQueryResponse(response=f"Response for {props.detector_id}!")
