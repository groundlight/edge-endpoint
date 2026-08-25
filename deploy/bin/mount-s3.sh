#!/bin/bash
# Mount an S3 bucket via mount-s3 (FUSE) on the host filesystem.
#
# This script runs inside a privileged sidecar container that has the host root
# filesystem bind-mounted at /host-root. It mounts the S3 bucket on
# /host-root/<mount_path> so the FUSE mount appears on the host and is
# accessible to other pods via hostPath volumes.
#
# Required environment variables:
#   S3_BUCKET   - S3 bucket name (e.g. pinamod-artifacts-public)
#   S3_REGION   - AWS region (e.g. us-west-2)
#   MOUNT_PATH  - Host path where the bucket will be mounted
#   CACHE_PATH  - Host path for the mount-s3 local disk cache

set -e

MOUNT_POINT="/host-root${MOUNT_PATH}"
CACHE_DIR="/host-root${CACHE_PATH}"

# Drain any stale or stacked FUSE mounts left from previous runs. A single
# umount is not enough: when a prior cleanup partially failed (e.g. the mount
# was busy or the daemon already gone), mount-s3 will happily mount on top of
# the existing entry, leaving a stack. Callers then traverse to the topmost
# layer; if that one is a zombie, every access returns ENOTCONN.
attempts=0
max_attempts=5
while ! stat "$MOUNT_POINT" >/dev/null 2>&1 \
   || mountpoint -q "$MOUNT_POINT" 2>/dev/null; do
    if [ "$attempts" -ge "$max_attempts" ]; then
        echo "WARNING: gave up draining mounts at $MOUNT_POINT after $attempts attempts" >&2
        break
    fi
    echo "Cleaning up stale mount at $MOUNT_POINT (attempt $((attempts + 1)))"
    umount -l "$MOUNT_POINT" 2>/dev/null \
        || fusermount -uz "$MOUNT_POINT" 2>/dev/null \
        || break
    attempts=$((attempts + 1))
done

mkdir -p "$MOUNT_POINT" "$CACHE_DIR"

echo "Mounting s3://$S3_BUCKET at $MOUNT_POINT (cache: $CACHE_DIR, region: $S3_REGION)"
mount-s3 "$S3_BUCKET" "$MOUNT_POINT" \
    --region "$S3_REGION" \
    --read-only \
    --cache "$CACHE_DIR" \
    --allow-other \
    --foreground &
MOUNT_PID=$!

# Release the mount on shutdown. Without a trap this never happens: bash is PID 1
# in the container's PID namespace, and PID 1 ignores signals that only have a
# default handler, so SIGTERM is discarded, Kubernetes waits out the full grace
# period, and mount-s3 is SIGKILLed without ever unmounting. That leaves a zombie
# behind on the host -- still listed in the mount table, but returning ENOTCONN to
# every reader -- for the next pod's drain loop above to clean up. Installing a
# handler gives SIGTERM something to run, so the mount goes away with the pod.
cleanup() {
    echo "Shutting down, unmounting $MOUNT_POINT"
    # Bound the clean-unmount attempts. Against a wedged (alive but unresponsive)
    # FUSE daemon a non-lazy umount can block, and we would never reach the
    # watchdog below -- burning the grace period and getting SIGKILLed without
    # unmounting, which is the outcome this trap exists to prevent. The liveness
    # probe now restarts the container on exactly that wedged case, so this path
    # is reachable. A busy-but-healthy mount returns EBUSY immediately, so the
    # common path is unaffected, and `umount -l` only detaches the name and
    # always returns promptly.
    timeout 5 umount "$MOUNT_POINT" 2>/dev/null \
        || timeout 5 fusermount -u "$MOUNT_POINT" 2>/dev/null \
        || umount -l "$MOUNT_POINT" 2>/dev/null \
        || echo "WARNING: every unmount attempt failed for $MOUNT_POINT; it will be left stale for the next pod to drain" >&2
    kill -TERM "$MOUNT_PID" 2>/dev/null || true
    # bash has no timeout on `wait`, so arm a watchdog: if mount-s3 is wedged and
    # doesn't exit, SIGKILL it rather than block until the termination grace
    # period expires (at which point we'd be SIGKILLed anyway, just 20s later).
    # `wait` still returns the instant mount-s3 exits, so the normal path is
    # unaffected.
    { sleep 10; kill -KILL "$MOUNT_PID" 2>/dev/null; } &
    watchdog=$!
    wait "$MOUNT_PID" 2>/dev/null || true
    kill "$watchdog" 2>/dev/null || true
    exit 0
}
trap cleanup TERM INT

# Verify the mount comes up healthy within 30s. Catches subtle failures like
# mount-s3 starting against the wrong bucket (empty listing) or a FUSE mount
# that established but isn't actually serving content. mount-s3 normally
# completes its initial mount within a few seconds.
#
# Note: this assumes the configured bucket is non-empty. A legitimately empty
# bucket would fail verification and the container would crash-loop with a
# misleading "mount verification failed" error. pinamod-artifacts-public is
# always populated in practice, so this tradeoff catches misconfigurations
# (typo'd bucket name, wrong region) at the cost of a hypothetical edge case.
verified=0
for _ in $(seq 1 30); do
    # Require the mount-s3 process we just spawned to still be alive: during a
    # rolling deploy, the previous pod's mount can still be propagated to the
    # host and pass the mountpoint+ls check even though our new mount-s3 has
    # already failed (e.g. "mountpoint is not empty").
    if kill -0 "$MOUNT_PID" 2>/dev/null \
       && mountpoint -q "$MOUNT_POINT" 2>/dev/null \
       && [ -n "$(ls -A "$MOUNT_POINT" 2>/dev/null)" ]; then
        verified=1
        break
    fi
    sleep 1
done

if [ "$verified" -ne 1 ]; then
    echo "ERROR: mount verification failed for $MOUNT_POINT (mount-s3 PID $MOUNT_PID)" >&2
    kill -TERM "$MOUNT_PID" 2>/dev/null || true
    wait "$MOUNT_PID" 2>/dev/null || true
    exit 1
fi

echo "Mount verified at $MOUNT_POINT"
wait "$MOUNT_PID"
