"""How inference pods choose their GPUs: from a node-wide placement ledger, or each pod on its own.

The chart resolves this to "ledger" for Triton pods on GPU devices that allow hostPath volumes and hostPID, which
spread their model instances across GPUs using a ledger in a shared host directory, and "none" otherwise. It stamps
the result on each pod template.
"""

import os
from enum import Enum


class GpuPlacement(str, Enum):
    NONE = "none"
    LEDGER = "ledger"


# Pod template annotation recording how an inference pod chooses its GPUs.
GPU_PLACEMENT_ANNOTATION = "groundlight.dev/gpu-placement"


def configured_gpu_placement() -> GpuPlacement:
    """The GPU placement new inference pods are deployed with (the chart's resolved `gpuPlacement`)."""
    return GpuPlacement(os.environ.get("GPU_PLACEMENT", GpuPlacement.NONE.value))
