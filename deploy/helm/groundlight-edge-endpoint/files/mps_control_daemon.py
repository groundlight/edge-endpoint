"""Runs the node's CUDA MPS control daemon for Triton inference pods.

Starts nvidia-cuda-mps-control in the foreground, checks that a CUDA client can join MPS through it, and
only then writes READY_MARKER into the pipe directory. Inference pods wait for the marker before joining
MPS (zuuul predictors/serving/triton/mps.py), so they never connect to a daemon that can't serve them.
The marker is removed when the daemon stops.

If the host driver install lacks the MPS binaries, MPS can't work on this node until the host changes. The
supervisor then writes UNAVAILABLE_MARKER, holding the reason, and stays up without becoming ready, so
inference pods run time-sliced at once instead of waiting for READY_MARKER.

`--self-test` runs the test client: it creates a CUDA context on every GPU and confirms the daemon lists
it as an MPS client.
"""

import ctypes
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

PIPE_DIRECTORY = Path(os.environ["CUDA_MPS_PIPE_DIRECTORY"])
READY_MARKER = PIPE_DIRECTORY / "gl-ready"
UNAVAILABLE_MARKER = PIPE_DIRECTORY / "gl-unavailable"
MPS_BINARIES = ("nvidia-cuda-mps-control", "nvidia-cuda-mps-server")
CONTROL_SOCKET = PIPE_DIRECTORY / "control"
STARTUP_TIMEOUT_SECONDS = 60
SELF_TEST_TIMEOUT_SECONDS = 120


def control(command: str) -> str:
    """Send one command to the running control daemon and return its reply."""
    result = subprocess.run(
        ["nvidia-cuda-mps-control"], input=command + "\n", capture_output=True, text=True, timeout=30, check=True
    )
    return result.stdout


def check_cuda(result: int, call: str) -> None:
    if result != 0:
        raise RuntimeError(f"{call} failed with CUDA error {result}")


def driver_version() -> str:
    """The host's NVIDIA driver version, or "unknown" if nvidia-smi can't report it."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return "unknown"
    return result.stdout.split("\n")[0].strip() or "unknown"


def self_test() -> None:
    """Create a CUDA context on every GPU and fail unless the daemon lists this process as an MPS client.

    CUDA silently runs without MPS when it can't reach the daemon, so a context alone proves nothing.
    """
    # Logged first so a failing node's logs name its driver.
    print(f"NVIDIA driver {driver_version()}", flush=True)
    cuda = ctypes.CDLL("libcuda.so.1")
    check_cuda(cuda.cuInit(0), "cuInit")
    count = ctypes.c_int()
    check_cuda(cuda.cuDeviceGetCount(ctypes.byref(count)), "cuDeviceGetCount")
    contexts = []
    for ordinal in range(count.value):
        device = ctypes.c_int()
        check_cuda(cuda.cuDeviceGet(ctypes.byref(device), ordinal), "cuDeviceGet")
        context = ctypes.c_void_p()
        check_cuda(cuda.cuCtxCreate_v2(ctypes.byref(context), 0, device), f"cuCtxCreate on GPU {ordinal}")
        contexts.append(context)

    clients = control("ps")
    client_pids = {line.split()[0] for line in clients.splitlines()[1:] if line.split()}
    if str(os.getpid()) not in client_pids:
        raise RuntimeError(f"Created CUDA contexts, but the MPS daemon does not list this process:\n{clients}")

    for context in contexts:
        check_cuda(cuda.cuCtxDestroy_v2(context), "cuCtxDestroy")
    print(f"Joined MPS on {count.value} GPU(s)", flush=True)


def remove_stale_sockets() -> None:
    """Remove the sockets a killed daemon leaves in the host directory.

    Otherwise the socket exists before the new daemon listens, and a client that connects too early runs without MPS.
    """
    for name in ("control", "control_privileged"):
        (PIPE_DIRECTORY / name).unlink(missing_ok=True)


def wait_for_control_daemon(daemon: subprocess.Popen) -> None:
    """Wait until the daemon answers on its control socket, not just until the socket file exists."""
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while True:
        if daemon.poll() is not None:
            raise RuntimeError(f"nvidia-cuda-mps-control exited with status {daemon.returncode} during startup")
        if CONTROL_SOCKET.exists():
            try:
                control("get_server_list")
                return
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                pass
        if time.monotonic() >= deadline:
            raise RuntimeError(f"the daemon didn't answer on {CONTROL_SOCKET} within {STARTUP_TIMEOUT_SECONDS}s")
        time.sleep(0.5)


def missing_binaries() -> list[str]:
    """The MPS binaries the NVIDIA runtime didn't inject into this container."""
    return [name for name in MPS_BINARIES if shutil.which(name) is None]


def wait_for_stop() -> None:
    """Sleep until SIGTERM or SIGINT."""
    stopping = []
    signal.signal(signal.SIGTERM, lambda signum, _frame: stopping.append(signum))
    signal.signal(signal.SIGINT, lambda signum, _frame: stopping.append(signum))
    while not stopping:
        time.sleep(1)


def stay_unavailable(reason: str) -> int:
    """Report MPS as unavailable on this node and idle until stopped.

    Restarting wouldn't help, so the pod stays up without becoming ready instead of crash-looping, and
    UNAVAILABLE_MARKER tells inference pods not to wait for the daemon.
    """
    print(f"CUDA MPS is unavailable on this node: {reason}", file=sys.stderr, flush=True)
    UNAVAILABLE_MARKER.write_text(reason + "\n")
    wait_for_stop()
    UNAVAILABLE_MARKER.unlink(missing_ok=True)
    return 0


def run_daemon() -> int:
    READY_MARKER.unlink(missing_ok=True)
    UNAVAILABLE_MARKER.unlink(missing_ok=True)
    missing = missing_binaries()
    if missing:
        return stay_unavailable(
            f"{' and '.join(missing)} not found. The host's NVIDIA driver install doesn't include the CUDA MPS "
            "binaries (on Ubuntu they're in the nvidia-compute-utils package for the driver version), so Triton "
            "pods run time-sliced."
        )
    remove_stale_sockets()
    daemon = subprocess.Popen(["nvidia-cuda-mps-control", "-f"])

    def stop(signum: int, _frame) -> None:
        # Withdraw the marker first so no new pod joins a daemon that is going away.
        READY_MARKER.unlink(missing_ok=True)
        daemon.send_signal(signum)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    try:
        wait_for_control_daemon(daemon)
        subprocess.run([sys.executable, __file__, "--self-test"], check=True, timeout=SELF_TEST_TIMEOUT_SECONDS)
    except BaseException:
        daemon.terminate()
        daemon.wait()
        raise

    READY_MARKER.touch()
    print(f"CUDA MPS daemon ready; wrote {READY_MARKER}", flush=True)
    returncode = daemon.wait()
    READY_MARKER.unlink(missing_ok=True)
    return returncode


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
    else:
        sys.exit(run_daemon())
