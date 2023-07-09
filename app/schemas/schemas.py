from typing import Optional, Union

from pydantic import BaseModel, Field, confloat, validator
import requests


class DetectorCreate(BaseModel):
    name: str = Field(description="Name of the detector")
    query: str = Field(description="Query associated with the detector")
    confidence_threshold: Optional[confloat(ge=0.0, le=1.0)] = Field(
        0.9,
        description=(
            "If the detector's prediction is below this confidence threshold, send the image query for human review."
        ),
    )
    pipeline_config: Optional[str] = Field(description="Pipeline config")


class ImageQueryCreate(BaseModel):
    """
    NOTE: For the `image` field, types BytesIO, BufferedReader, Image.Image
    and numpy.ndarray are not JSON compatible. For now we are only supporting
    str and bytes types although the Groundlight SDK accepts all the above.
    Reference: https://fastapi.tiangolo.com/tutorial/encoder/
    """

    detector_name: str = Field(description="Detector name")
    image: Union[str, bytes] = Field(
        description="Image to submit to the detector. If the image is a string, it is assumed to be a URL."
    )
    wait: Optional[float] = Field(None, description="How long to wait for a confident response (seconds)")

    @validator("image")
    def validate_image(cls, value):
        return cls._sanitize_image_input(image=value)

    @staticmethod
    def _sanitize_image_input(image: Union[str, bytes]) -> bytes:
        """Sanitizes the image input to be a bytes object.

        Args:
            image (Union[str, bytes]): Image input. If the image is a string, it is assumed to be a URL.

        Raises:
            ValueError: In case the image type is not supported.

        Returns:
            bytes: Image bytes.
        """
        if isinstance(image, str):
            # If the image is a URL, get the image bytes
            return requests.get(image, timeout=5).content
        elif isinstance(image, bytes):
            return image

        raise ValueError(f"Unsupported input image type: {type(image)}")
