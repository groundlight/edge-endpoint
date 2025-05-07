DEFAULT_PATIENCE_TIME: int = 30  # Default patience time in seconds

CONNECTION_STATUS_TTL_SECS = 0.5  # Number of seconds to cache the connection status
CONNECTION_TEST_HOST, CONNECTION_TEST_PORT = "8.8.8.8", 53  # Google's DNS server
SOCKET_TIMEOUT = 1  # Maximum number of seconds to attempt a connection

DEFAULT_POLLING_INITIAL_DELAY = 0.25
DEFAULT_POLLING_EXPONENTIAL_BACKOFF = 1.3
DEFAULT_POLLING_TIMEOUT_SEC = float("inf")
