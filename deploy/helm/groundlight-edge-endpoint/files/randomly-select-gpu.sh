#!/bin/bash

# Randomly selects a GPU from available GPUs and outputs the selected GPU ID
# Used for evenly distributing inference pods across multiple GPUs
# Usage: SELECTED_GPU=$(./randomly-select-gpu.sh)

if command -v nvidia-smi >/dev/null 2>&1; then
  GPU_COUNT=$(nvidia-smi --list-gpus | wc -l)
  echo "Detected $GPU_COUNT GPU(s)" >&2
  
  if [ "$GPU_COUNT" -eq 1 ]; then
    echo "Single GPU detected, using GPU 0" >&2
    echo "0"  # Output the selected GPU ID
  elif [ "$GPU_COUNT" -gt 1 ]; then
    # Randomly select a GPU (0 to GPU_COUNT-1)
    SELECTED_GPU=$((RANDOM % GPU_COUNT))
    echo "Multiple GPUs detected, randomly selected GPU $SELECTED_GPU out of $GPU_COUNT" >&2
    echo "$SELECTED_GPU"  # Output the selected GPU ID
  else
    echo "No GPUs detected, running on CPU" >&2
    echo "Running on CPU (no GPU selected)" >&2
    echo ""  # Output empty string for CPU mode
  fi
else
  echo "nvidia-smi not available, running on CPU" >&2
  echo "Running on CPU (no GPU selected)" >&2
  echo ""  # Output empty string for CPU mode
fi
