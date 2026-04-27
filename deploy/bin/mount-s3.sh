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

# Unmount any stale mount from a previous run before mkdir, since stat() on an
# orphaned FUSE endpoint fails with ENOTCONN and would break `mkdir -p` below.
if ! stat "$MOUNT_POINT" >/dev/null 2>&1 || mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
    echo "Cleaning up stale mount at $MOUNT_POINT"
    umount "$MOUNT_POINT" 2>/dev/null || fusermount -u "$MOUNT_POINT" 2>/dev/null || true
fi

mkdir -p "$MOUNT_POINT" "$CACHE_DIR"

echo "Mounting s3://$S3_BUCKET at $MOUNT_POINT (cache: $CACHE_DIR, region: $S3_REGION)"
mount-s3 "$S3_BUCKET" "$MOUNT_POINT" \
    --region "$S3_REGION" \
    --read-only \
    --cache "$CACHE_DIR" \
    --allow-other \
    --foreground
