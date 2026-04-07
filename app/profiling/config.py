import os

PROFILING_ENABLED: bool = os.environ.get("ENABLE_PROFILING", "false").lower() == "true"
