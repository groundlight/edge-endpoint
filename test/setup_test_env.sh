#!/bin/bash 

# This script is for setting up the test environment for running motion detection tests locally. 
# It will create a YAML config as an environment variable. 
# Currently, this is the best way to run the tests locally, and github actions in 
# .github/workflows/pipeline.yaml also runs motion detection tests in a similar fashion by injecting a 
# YAML block. 

# NOTE: The detectors have already been created under the "prod-biggies" account, so make sure to get 
# an API token from this account if you don't have one already. 

# Use the script as follows:
# > docker build --target production-image --tag groundlight-edge .
# > source test/setup_test_env.sh
# > docker run -e LOG_LEVEL=DEBUG -e EDGE_CONFIG=$EDGE_CONFIG -e GROUNDLIGHT_API_TOKEN --rm -it -p 6717:6717 groundlight-edge

# Then in another terminal, run the motion detection tests:
# > poetry run pytest -vs test/api/test_motdet.py

EDGE_CONFIG="
motion_detection:
    - detector_id: 'det_2UOxalD1gegjk4TnyLbtGggiJ8p'
      motion_detection_enabled: true
      motion_detection_percentage_threshold: 5.0
      motion_detection_val_threshold: 50
      motion_detection_max_time_between_images: 30
    
    - detector_id: 'det_2UOxao4HZyB9gv4ZVtwMOvdqgh9'
      motion_detection_enabled: true
      motion_detection_percentage_threshold: 0.0
      motion_detection_val_threshold: 0
      motion_detection_max_time_between_images: 30
"

export EDGE_CONFIG