import GPUtil
import psutil
import logging

logger = logging.getLogger(__name__)


def get_cpu_usage():
    return psutil.cpu_percent(interval=1)


def get_memory_usage():
    return psutil.virtual_memory().percent


def get_gpu_count():
    return len(GPUtil.getGPUs())


def get_gpu_usage():
    logger.info(f"Getting GPU usage: {GPUtil.getGPUs()}")
    return GPUtil.getGPUs()
