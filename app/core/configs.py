"""SDK-backed edge endpoint configuration model aliases."""

from groundlight.edge import (
    DetectorConfig,
    EdgeEndpointConfig,
    GlobalConfig,
    InferenceConfig,
)

EdgeInferenceConfig = InferenceConfig
RootEdgeConfig = EdgeEndpointConfig

__all__ = [
    "DetectorConfig",
    "EdgeEndpointConfig",
    "GlobalConfig",
    "InferenceConfig",
    "EdgeInferenceConfig",
    "RootEdgeConfig",
]
