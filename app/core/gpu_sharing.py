"""How inference pods share a GPU: time-sliced CUDA contexts, or one CUDA MPS server per node.

The chart resolves `gpuSharing` to the mode pods actually get (MPS only for Triton pods on x86_64 GPU
devices) and stamps it on each pod template.
"""

import os
from enum import Enum


class GpuSharing(str, Enum):
    NONE = "none"
    MPS = "mps"


# Pod template annotation recording how an inference pod shares the GPU.
GPU_SHARING_ANNOTATION = "groundlight.dev/gpu-sharing"


def configured_gpu_sharing() -> GpuSharing:
    """The GPU sharing new inference pods are deployed with (the chart's resolved `gpuSharing`)."""
    return GpuSharing(os.environ.get("GPU_SHARING", GpuSharing.NONE.value))
