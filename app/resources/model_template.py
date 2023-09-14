import json
import os

import numpy as np
import triton_python_backend_utils as pb_utils
import yaml
from PIL import Image

from predictors.datasets.dataset import Example
from predictors.pipeline.pipeline import Pipeline


def request_to_pil_image(request: "pb_utils.InferenceRequest") -> Image.Image:
    """
    Assumes that the input tensor is a 3-channel (CHW) uint8 RGB image with values in [0, 255].
    """
    numpy_image = pb_utils.get_input_tensor_by_name(request, "image").as_numpy()
    return Image.fromarray(numpy_image, mode="RGB")


def load_buffer_from_file(model_dir: str, filename: str = "model.buf") -> bytes:
    with open(os.path.join(model_dir, filename), "rb") as f:
        return f.read()


def get_config_parameter_by_name(model_config: dict, name: str) -> str:
    return model_config["parameters"][name]["string_value"]


class TritonPythonModel:
    """
    Code for integrating Groundlight Pipelines with Triton Inference Server.

    Every Python model that is run on triton inference server must have "TritonPythonModel" as the class name.
    """

    def initialize(self, args: dict[str, str]) -> None:
        """`initialize` is called only once when the model is being loaded.
        Implementing `initialize` function is optional. This function allows
        the model to initialize any state associated with this model.

        Parameters
        ----------
        args : dict
          Both keys and values are strings. The dictionary keys and values are:
          * model_config: A JSON string containing the model configuration
          * model_instance_kind: A string containing model instance kind (e.g. gpu, cpu)
          * model_instance_device_id: A string containing model instance device ID (i.e. which GPU)
          * model_repository: Model repository path
          * model_name: Model name
          * model_version: Model version
        """
        print(args)
        # You must parse model_config. JSON string is not parsed here
        self.model_config = model_config = json.loads(args["model_config"])

        # Get output configuration
        output_score_config = pb_utils.get_output_config_by_name(model_config, "score")
        output_confidence_config = pb_utils.get_output_config_by_name(model_config, "confidence")
        output_probability_config = pb_utils.get_output_config_by_name(model_config, "probability")

        # Convert Triton types to numpy types
        self.output_score_dtype = pb_utils.triton_string_to_numpy(output_score_config["data_type"])
        self.output_confidence_dtype = pb_utils.triton_string_to_numpy(output_confidence_config["data_type"])
        self.output_probability_dtype = pb_utils.triton_string_to_numpy(output_probability_config["data_type"])

        # Setup pipeline
        model_dir = os.path.join(args["model_repository"], args["model_version"])
        buffer = load_buffer_from_file(model_dir)

        pipeline_config: str = "{pipeline_config}"  # This is a template value that will be replaced
        pipeline_config_dict = yaml.safe_load(pipeline_config)
        pipeline_config_dict: dict = (
            pipeline_config_dict if isinstance(pipeline_config_dict, dict) else {"name": pipeline_config_dict}
        )

        self.pipeline = Pipeline.create(
            buffer=buffer,
            text_query="example text query",
            **pipeline_config_dict,
        )

    def execute(self, requests: list["pb_utils.InferenceRequest"]) -> list["pb_utils.InferenceResponse"]:
        """`execute` must be implemented in every Python model. `execute`
        function receives a list of pb_utils.InferenceRequest as the only
        argument. This function is called when an inference is requested
        for this model.

        Parameters
        ----------
        requests : list
          A list of pb_utils.InferenceRequest

        Returns
        -------
        list
          A list of pb_utils.InferenceResponse. The length of this list must
          be the same as `requests`
        """

        responses = []

        # Every Python backend must iterate through list of requests and create
        # an instance of pb_utils.InferenceResponse class for each of them.
        # Reusing the same pb_utils.InferenceResponse object for multiple
        # requests may result in segmentation faults. You should avoid storing
        # any of the input Tensors in the class attributes as they will be
        # overridden in subsequent inference requests. You can make a copy of
        # the underlying NumPy array and store it if it is required.
        for request in requests:
            # Get PIL image from request
            image = request_to_pil_image(request)

            preds = self.pipeline.run(
                examples=[Example(data=image, example_id=None, annotations_requested=[])],
                return_rois=False,
            )

            prob: np.ndarray | None = preds.probabilities
            if prob is None:
                raise ValueError("Pipeline did not return probabilities")

            # Create output tensors. You need pb_utils.Tensor
            # objects to create pb_utils.InferenceResponse.
            out_tensor_score = pb_utils.Tensor("score", prob.astype(self.output_score_dtype))
            out_tensor_confidence = pb_utils.Tensor("confidence", prob.astype(self.output_confidence_dtype))
            out_tensor_probability = pb_utils.Tensor("probability", prob.astype(self.output_probability_dtype))

            # Create InferenceResponse. You can set an error here in case
            # there was a problem with handling this inference request.
            inference_response = pb_utils.InferenceResponse(
                output_tensors=[
                    out_tensor_score,
                    out_tensor_confidence,
                    out_tensor_probability,
                ]
            )
            responses.append(inference_response)

        return responses

    def finalize(self) -> None:
        del self.pipeline
