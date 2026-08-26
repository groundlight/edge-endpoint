"""Exit 0 if the given path is a mount point, else 1. Used as the mount-s3 liveness probe."""

import os
import sys


def is_mount_point(path: str, mounts_file: str = "/proc/mounts") -> bool:
    """Return True if path appears as a mount destination in /proc/mounts."""
    real = os.path.realpath(path)
    encoded = real.replace(" ", r"\040")
    try:
        with open(mounts_file, encoding="utf-8") as mounts:
            return any(len(parts := line.split()) > 1 and parts[1] == encoded for line in mounts)
    except FileNotFoundError:
        return False


def main(argv: list[str] | None = None) -> int:
    """Probe whether argv[1] (or CHECK_MOUNT_PATH) is currently mounted."""
    args = sys.argv[1:] if argv is None else argv
    path = args[0] if args else os.environ.get("CHECK_MOUNT_PATH", "")
    if not path:
        print("usage: python -m app.runtime.check_s3_mount <path>", file=sys.stderr)
        return 2
    return 0 if is_mount_point(path) else 1


if __name__ == "__main__":
    sys.exit(main())
