API_VERSION = "v1"
API_PREFIX = "/device-api"
API_BASE_PATH = f"{API_PREFIX}/{API_VERSION}"


def path_prefix(name: str) -> str:
    return f"/{name}"


def tag(name: str) -> str:
    return name


def full_path(name: str) -> str:
    return f"{API_BASE_PATH}{path_prefix(name)}"
