#!/bin/bash

# Randomly selects a GPU from available GPUs and outputs the selected GPU ID
# Used for evenly distributing inference pods across multiple GPUs
# Usage: SELECTED_GPU=$(./randomly-select-gpu.sh)

set -e

# This script expects the INFERENCE_FLAVOR environment variable to be set to either "gpu" or "cpu".
# If not set, fail loudly.
if [ -z "$INFERENCE_FLAVOR" ]; then
  echo "ERROR: INFERENCE_FLAVOR environment variable is not set. Please set it to 'gpu' or 'cpu'." >&2
  exit 1
fi

if [ "$INFERENCE_FLAVOR" = "gpu" ]; then
  if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "ERROR: INFERENCE_FLAVOR is set to 'gpu' but 'nvidia-smi' is not available. Failing." >&2
    exit 1
  fi

  GPU_COUNT=$(nvidia-smi --list-gpus | wc -l)
  if [ "$GPU_COUNT" -lt 1 ]; then
    echo "ERROR: INFERENCE_FLAVOR is 'gpu' but no GPUs were detected by nvidia-smi. Failing." >&2
    exit 1
  fi

  echo "Detected $GPU_COUNT GPU(s)" >&2

  if [ "$GPU_COUNT" -eq 1 ]; then
    echo "Single GPU detected, using GPU 0" >&2
    echo "0"
  else
    SELECTED_GPU=$((RANDOM % GPU_COUNT))
    echo "Multiple GPUs detected, randomly selected GPU $SELECTED_GPU out of $GPU_COUNT" >&2
    echo "$SELECTED_GPU"
  fi

elif [ "$INFERENCE_FLAVOR" = "cpu" ]; then
  echo "INFERENCE_FLAVOR is set to 'cpu'. No GPU will be selected." >&2
  echo ""
else
  echo "ERROR: INFERENCE_FLAVOR is set to an unknown value: '$INFERENCE_FLAVOR'. Must be 'gpu' or 'cpu'." >&2
  exit 1
fi
