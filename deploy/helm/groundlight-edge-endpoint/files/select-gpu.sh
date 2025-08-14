#!/bin/bash

# Intelligent GPU Selection for Kubernetes Deployment
# Selects GPU with lowest memory usage and outputs the selected GPU ID
# Usage: SELECTED_GPU=$(./select-gpu.sh)

# NOTE: In practice, this selection method doesn't seem to work as well as `randomly-select-gpu.sh`. 
# The problem with this approach is that there is a significant delay between the time a GPU is 
# selected and the VRAM is actually allocated on that GPU. Therefore, if you start many inference pods 
# at the same time (as we often do), the result is that many pods get assigned to the same GPU, and 
# some the pods will crash and have to restart. 
# Perhaps there is a way to adapt this method to work better, but for now we'll leave this script here unused. 

if command -v nvidia-smi >/dev/null 2>&1; then
  GPU_COUNT=$(nvidia-smi --list-gpus | wc -l)
  echo "Detected $GPU_COUNT GPU(s)" >&2
  
  if [ "$GPU_COUNT" -eq 1 ]; then
    echo "Single GPU detected, using GPU 0" >&2
    echo "0"  # Output the selected GPU ID
  elif [ "$GPU_COUNT" -gt 1 ]; then
    # Find GPU with lowest memory usage
    BEST_GPU=0
    LOWEST_MEMORY=999999
    
    for i in $(seq 0 $((GPU_COUNT-1))); do
      MEMORY_USED=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i $i)
      echo "GPU $i: ${MEMORY_USED}MB used" >&2
      
      if [ "$MEMORY_USED" -lt "$LOWEST_MEMORY" ]; then
        LOWEST_MEMORY=$MEMORY_USED
        BEST_GPU=$i
      fi
    done
    
    echo "Selected GPU $BEST_GPU with lowest memory usage: ${LOWEST_MEMORY}MB" >&2
    echo "Using GPU $BEST_GPU" >&2
    echo "$BEST_GPU"  # Output the selected GPU ID
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

