#!/bin/bash 

# This script is for setting up the test environment for running motion detection tests locally. 
# It will create a YAML config as an environment variable. 
# Currently, this is the best way to run the tests locally, and github actions in 
# .github/workflows/pipeline.yaml also runs motion detection tests in a similar fashion by injecting a 
# YAML block. 

# Run the script as follows:
# > ./test/setup_test_env.sh
# > poetry run pytest -vs test/test_motdet.py


EDGE_CONFIG=$(echo "
motion-detection:
    - detector_id: ''
    - enabled: true
    - percentage_threshold: 5.0
    - val_threshold: 50
    - max_time_between_images: 30
" | base64 -w 0)

export EDGE_CONFIG