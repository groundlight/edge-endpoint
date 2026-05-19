"""Shared constants for app_benchmark.

Lives here (rather than inside lenses.py or detectors.py) so both modules
can import it without introducing a directional dependency between them.
"""

# Resolution used for the downstream binary stage in a `bbox_to_binary`
# lens — both at worker runtime (the cached binary ndarray submitted N
# times per frame) and at detector provisioning (priming images need to
# match what the model serves at runtime).
BINARY_DOWNSTREAM_SIZE: tuple[int, int] = (224, 224)
