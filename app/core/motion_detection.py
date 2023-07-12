import asyncio
from asyncio import Lock
from typing import List, Optional

import faiss
import numpy as np
from img2vec_pytorch import Img2Vec
from model import ImageQuery
from PIL import Image
from pydantic import BaseSettings, Field


class MotdetConfig(BaseSettings):
    detector_ids: List[str] = Field(..., description="List of Detector ID's")

    # Fixed index type for all detectors. If we ever have a reason to specify different index types
    # for different detectors, we can update this in the YAML config file.
    # For more options on index types, see: https://github.com/facebookresearch/faiss/wiki/The-index-factory
    # This index corresponds to a flat index (i.e., returns exact results and not approximate) and uses
    # an inverted file with 256 cells.
    index_type: Optional[str] = Field("IVF256, Flat", description="Index type. This is fixed for all detectors.")


class MotionDetector:
    """Asynchronous motion detector.
    This is a wrapper around MotionDetector that exposes an asynchronous
    execution of `motion_detected` method. Although this method need not be asynchronous
    from a performance standpoint, we want it to be `async` since it will be
    invoked asynchronously from the API.
    """

    def __init__(
        self,
        index_type: str,
        image_dim: int = 1280,
        embedding_model: str = "efficientnet-b0",
        similarity_threshold: float = 10.0,
        max_index_size: int = 1000,
    ):
        self._previous_image = None
        self.similarity_threshold = similarity_threshold
        self.max_index_size = max_index_size
        self.lock = Lock()
        self._image_query_response = None
        self._embedder = Img2Vec(cuda=False, model=embedding_model)
        self._ids_to_eject_range = range(0, max_index_size // 2)

        self._index = faiss.index_factory(image_dim, index_type)

    def _get_image_embedding(
        self, image: np.ndarray, resize: bool = False, resizing_dims: tuple = (224, 224)
    ) -> np.ndarray:
        """
        Get the embedding of the given image.
        Args:
            image: Image for which to create a vector embedding.
            resize: Indicates whether to resize the image before creating the embedding.
                resizing is necessary (for now) since the embedding model `efficinent-net`
                performs best on images with the dimension it expects.
            resizing_dims: Dimensions to resize the image to.

        Returns:
            The embedding of the given image.
        """
        image_pil = Image.fromarray(image.astype("uint8")).convert("RGB")
        if resize:
            image_pil = image_pil.resize(resizing_dims, Image.ANTIALIAS)

        return self._embedder.get_vec(image_pil)

    @property
    def image_query_response(self):
        return self._image_query_response

    @image_query_response.setter
    def image_query_response(self, response: ImageQuery):
        self._image_query_response = response

    def add_image(self, image: np.ndarray) -> None:
        """
        Add the given image to the index.
        Args:
            image: Image to add to the index. This is not the image itself,
            but its embedding representation.

        Returns:
            None
        """
        self._index.add(image)

        if self._index.ntotal == self.max_index_size:
            ids_to_remove = np.arange(self._ids_to_eject_range.start, self._ids_to_eject_range.stop)
            selector = faiss.IDSelectorBatch(ids_to_remove.size, faiss.swig_ptr(ids_to_remove))
            self._index.remove_ids(selector)

            self._ids_to_eject_range = range(
                self._ids_to_eject_range.stop, self._ids_to_eject_range.stop + self.max_index_size // 2
            )

    def knn_search(self, image: np.ndarray, k: int = 1) -> np.ndarray:
        """
        Search for the nearest neighbors of the given image.
        Args:
            image: Image to search for.
            k: Number of nearest neighbors to return.

        Returns:
            np.ndarray containing distances of shape (1, k).
            If we were to run search on a batch of images, the
            output would have shape (batch_size, k).
            NOTE: The distances are sorted in ascending order.

        """

        distances, _ = self._index.search(image, k)
        return distances

    async def motion_detected(self, new_img: np.ndarray) -> bool:
        """
        Check if motion was detected in the given image.
        Args:
            new_img: Image to check for motion as numpy array
        Returns:
            True if motion was detected, False otherwise.
        """
        async with self.lock:
            image_embedding = self._get_image_embedding(image=new_img)
            self._index.add(image_embedding)
            if not self._index.ntotal:
                return True

            distances = self.knn_search(image_embedding)

            return distances[0][0] < self.similarity_threshold


class MotionDetectionManager:
    def __init__(self, config: MotdetConfig):
        self.detectors = {id: MotionDetector(index_type=config.index_type) for id in config.detector_ids}

        self.tasks = {id: [] for id in config.detector_ids}

    def update_image_query_response(self, detector_id: str, response: ImageQuery) -> None:
        self.detectors[detector_id].image_query_response = response

    def get_image_query_response(self, detector_id: str) -> ImageQuery:
        return self.detectors[detector_id].image_query_response

    async def run_motion_detection(self, detector_id: str, image: np.ndarray) -> bool:
        """
        Submits a coroutine to run motion detection on the given image in the background.
        That means motion detection will be run concurrently with the existing tasks in the event loop.
        This is useful because it allows us to run motdet in parallel for multiple different detectors.

        Args:
            detector_id: ID of the detector to run motion detection on.
            image: Image to run motion detection on.

        Returns:
            True if motion was detected, False otherwise.

        """

        if detector_id not in self.detectors.keys():
            raise ValueError(f"Detector ID {detector_id} not found")

        task = asyncio.create_task(asyncio.to_thread(self.detectors[detector_id].motion_detected(new_img=image)))
        self.tasks[detector_id].append(task)

        self.get_result(task=task)

    async def get_result(self, task: asyncio.task) -> bool:
        """
        Wait for the motion detection task to finish and return the result
        """
        return await task
