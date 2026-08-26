"""Mount an S3 bucket with mount-s3 (FUSE) on the host filesystem.

Runs in the privileged mount-s3 sidecar. The host root is bind-mounted at
/host-root; the FUSE mount is created at /host-root/<MOUNT_PATH> so other pods
can consume it via hostPath.

AWS's mount-s3 binary does its own TLS to S3. That crypto is outside the
Chainguard FIPS Python runtime; see the FIPS image comments.
"""

import ctypes
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from app.runtime.check_s3_mount import is_mount_point

MNT_DETACH = 2  # linux umount2(2) MNT_DETACH / lazy unmount
MAX_DRAIN_ATTEMPTS = 5
VERIFY_SECONDS = 30


def _libc() -> ctypes.CDLL:
    """Return the process libc for umount2."""
    return ctypes.CDLL(None, use_errno=True)


def lazy_unmount(path: str) -> bool:
    """Lazy-unmount path via umount2. Return True if the syscall succeeded."""
    libc = _libc()
    if libc.umount2(path.encode(), MNT_DETACH) == 0:
        return True
    err = ctypes.get_errno()
    print(f"umount2({path}) failed: {os.strerror(err)} ({err})", file=sys.stderr)
    return False


def path_statable(path: str) -> bool:
    """Return True if stat(2) on path succeeds."""
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def needs_drain(mount_point: str) -> bool:
    """Return True if mount_point is a live mount or a zombie path that cannot be statted."""
    if is_mount_point(mount_point):
        return True
    return os.path.lexists(mount_point) and not path_statable(mount_point)


def drain_stale_mounts(mount_point: str) -> None:
    """Unmount stacked/stale FUSE mounts so a new mount-s3 is not layered on a zombie."""
    attempts = 0
    while needs_drain(mount_point):
        if attempts >= MAX_DRAIN_ATTEMPTS:
            print(
                f"WARNING: gave up draining mounts at {mount_point} after {attempts} attempts",
                file=sys.stderr,
            )
            break
        print(f"Cleaning up stale mount at {mount_point} (attempt {attempts + 1})")
        if not lazy_unmount(mount_point):
            break
        attempts += 1


def mount_s3_argv(bucket: str, mount_point: str, region: str, cache_dir: str) -> list[str]:
    """Build the mount-s3 argv, using the glibc loader when the FIPS image staged it."""
    args = [
        bucket,
        mount_point,
        "--region",
        region,
        "--read-only",
        "--cache",
        cache_dir,
        "--allow-other",
        "--foreground",
    ]
    loader = "/opt/aws-mount-s3/lib64/ld-linux-x86-64.so.2"
    binary = "/opt/aws-mount-s3/bin/mount-s3"
    if os.path.isfile(loader) and os.path.isfile(binary):
        return [loader, "--library-path", "/opt/aws-mount-s3/lib", binary, *args]
    return ["mount-s3", *args]


def listing_nonempty(mount_point: str) -> bool:
    """Return True if the mount point lists at least one entry."""
    try:
        return bool(os.listdir(mount_point))
    except OSError:
        return False


def pid_alive(pid: int) -> bool:
    """Return True if the process is still running."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def main() -> int:
    """Drain stale mounts, start mount-s3, verify, then wait on the child."""
    bucket = os.environ["S3_BUCKET"]
    region = os.environ["S3_REGION"]
    mount_path = os.environ["MOUNT_PATH"]
    cache_path = os.environ["CACHE_PATH"]

    mount_point = f"/host-root{mount_path}"
    cache_dir = f"/host-root{cache_path}"

    drain_stale_mounts(mount_point)
    Path(mount_point).mkdir(parents=True, exist_ok=True)
    Path(cache_dir).mkdir(parents=True, exist_ok=True)

    print(f"Mounting s3://{bucket} at {mount_point} (cache: {cache_dir}, region: {region})")
    proc = subprocess.Popen(mount_s3_argv(bucket, mount_point, region, cache_dir))

    verified = False
    for _ in range(VERIFY_SECONDS):
        if pid_alive(proc.pid) and is_mount_point(mount_point) and listing_nonempty(mount_point):
            verified = True
            break
        time.sleep(1)

    if not verified:
        print(
            f"ERROR: mount verification failed for {mount_point} (mount-s3 PID {proc.pid})",
            file=sys.stderr,
        )
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        return 1

    print(f"Mount verified at {mount_point}")
    return proc.wait()


if __name__ == "__main__":
    sys.exit(main())
