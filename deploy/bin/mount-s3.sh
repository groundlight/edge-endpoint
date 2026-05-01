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

# Verify the mount comes up healthy within 30s. Catches subtle failures like
# mount-s3 starting against the wrong bucket (empty listing) or a FUSE mount
# that established but isn't actually serving content. mount-s3 normally
# completes its initial mount within a few seconds.
verified=0
for _ in $(seq 1 30); do
    if mountpoint -q "$MOUNT_POINT" 2>/dev/null \
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
