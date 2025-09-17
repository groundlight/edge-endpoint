import logging
import os

class ContextFilter(logging.Filter):
    def __init__(self, component):
        super().__init__()
        self.component = component or ""

    def filter(self, record):
        record.component = self.component
        return True

def create_logger(name: str, is_test: bool = False, component: str = None) -> logging.Logger:
    
    # Logger
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    
    # Avoid adding handlers repeatedly
    if not logger.handlers:
    
        # Add filter to inject `component`
        context_filter = ContextFilter(component)
        logger.addFilter(context_filter)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter('[%(name)s %(component)s] %(message)s')
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

        if is_test:
            console_handler.setLevel(logging.DEBUG)
        else:
            # File handler - use a generic log location for edge-endpoint
            log_dir = os.getenv("LOG_DIR", "/var/log/edge-endpoint")
            os.makedirs(log_dir, exist_ok=True)
            file_handler = logging.FileHandler(f"{log_dir}/edge-endpoint.log", mode="a")
            file_handler.setLevel(logging.DEBUG)
            file_formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] [%(name)s %(component)s] [tid: %(thread)d] %(message)s')
            file_handler.setFormatter(file_formatter)
            logger.addHandler(file_handler)

            # Add Splunk handler if configured
            if os.getenv("SPLUNK_HEC_TOKEN") and os.getenv("SPLUNK_HEC_URL"):
                try:
                    from app.utils.splunk_handler import SplunkHECHandler
                    splunk_handler = SplunkHECHandler(
                        source="edge-endpoint",
                        sourcetype="edge:endpoint:logs"
                    )
                    splunk_handler.setLevel(logging.DEBUG)
                    splunk_formatter = logging.Formatter('%(message)s')
                    splunk_handler.setFormatter(splunk_formatter)
                    splunk_handler.addFilter(context_filter)
                    logger.addHandler(splunk_handler)
                    logger.info(f"Splunk HEC handler added for logger: {name}")
                except Exception as e:
                    logger.warning(f"Could not add Splunk handler: {e}")
            else:
                logger.info("Splunk HEC handler not configured, skipping")

    return logger


