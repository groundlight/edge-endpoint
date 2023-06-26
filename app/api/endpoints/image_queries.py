from fastapi import APIRouter, Depends
from starlette.requests import Request
from app.core.image_utils import get_numpy_image
from app.schemas.schemas import ImageQueryCreate, ImageQueryResponse
import logging 


logger = logging.getLogger(__name__)

def get_groundlight_instance(request: Request):
    return request.app.state.groundlight


def get_motion_detector_instance(request: Request):
    return request.app.state.motion_detector


router = APIRouter()

@router.post("", response_model=ImageQueryResponse)
async def post_image_query(
    props: ImageQueryCreate,
    gl: Depends = Depends(get_groundlight_instance),
    motion_detector: Depends = Depends(get_motion_detector_instance),
):
    """
    Submit an image query to the detector.
    """

    detector_name = props.detector_name
    image = get_numpy_image(image_filename=props.image)
    wait_time = props.wait if "wait" in props else None

    detector = gl.get_detector_by_name(name=detector_name)

    async with motion_detector.lock:
        # Use the motion detector with thread safety
        motion_detected = await motion_detector.motion_detected(new_img=image)
        if motion_detected:
            image_query = gl.submit_image_query(detector=detector, image=image, wait=wait_time)
            response = ImageQueryResponse(
                created_at=image_query.created_at, detector_id=image_query.detector_id, result=image_query.result
            )
            motion_detector.image_query_response = response
            logger.info("Motion detected")
            return response 
    
    logger.info("No motion detected")
    return motion_detector.image_query_response

