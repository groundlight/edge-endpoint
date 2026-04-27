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

mkdir -p "$MOUNT_POINT" "$CACHE_DIR"

# Unmount if stale mount exists from a previous run
if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
    echo "Unmounting stale mount at $MOUNT_POINT"
    umount "$MOUNT_POINT" || fusermount -u "$MOUNT_POINT" || true
fi

echo "Mounting s3://$S3_BUCKET at $MOUNT_POINT (cache: $CACHE_DIR, region: $S3_REGION)"
mount-s3 "$S3_BUCKET" "$MOUNT_POINT" \
    --region "$S3_REGION" \
    --read-only \
    --cache "$CACHE_DIR" \
    --allow-other \
    --foreground
