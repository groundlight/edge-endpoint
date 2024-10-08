#!/bin/bash

# This script is for setting up the test environment for tests locally.
# It will create a YAML config as an environment variable.
# Currently, this is the best way to run the tests locally, and it works to run the tests in github actions as well.

# NOTE: The detectors have already been created under the "prod-biggies" account, so make sure to get
# an API token from this account if you don't have one already.

# Use the script as follows:
# > docker build --tag edge-endpoint .
# > source test/setup_plain_test_env.sh
# > docker run --name groundlight-edge \
#      -e LOG_LEVEL=DEBUG \
#      -e EDGE_CONFIG \
#      --rm -it -p 6717:6717 edge-endpoint

# Then in another terminal, run the motion detection tests:
# > poetry run pytest -vs test/api/test_motdet.py

# The following detector IDs correspond to the "dog" and "cat" detectors.
# More information on these detectors in the testing file test/api/test_motdet.py

EDGE_CONFIG=$(cat <<- EOM
motion_detection_templates:
  default:
    enabled: true
    val_threshold: 50
    percentage_threshold: 5.0
    max_time_between_images: 45

  super-sensitive:
    enabled: true
    val_threshold: 5
    percentage_threshold: 0.05
    max_time_between_images: 45

  disabled:
    enabled: false

local_inference_templates:
  default:
    enabled: true
  disabled:
    enabled: false

detectors:
  - detector_id: 'det_2UOxalD1gegjk4TnyLbtGggiJ8p'
    motion_detection_template: 'disabled'
    local_inference_template: 'disabled'

  - detector_id: 'det_2UOxao4HZyB9gv4ZVtwMOvdqgh9'
    motion_detection_template: 'disabled'
    local_inference_template: 'disabled'
    edge_only_inference: true
EOM
)

export EDGE_CONFIG