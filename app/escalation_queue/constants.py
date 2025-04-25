DEFAULT_QUEUE_BASE_DIR = "/opt/groundlight/queue"  # Default base directory for escalation queue files.
MAX_QUEUE_FILE_LINES = 200  # Maximum number of lines written to each escalation queue file.
MAX_RETRY_ATTEMPTS = 3  # Maximum number of times that an escalation will be attempted before giving up.

CONNECTION_TEST_HOST, CONNECTION_TEST_PORT = "8.8.8.8", 53  # Google's DNS server
CONNECTION_TIMEOUT = 1  # Number of seconds to attempt to connect
CONNECTION_STATUS_TTL_SECS = 2  # Number of seconds to cache the connection status TODO do we want to cache at all?
