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

# Then in another terminal, run the tests:
# > make test-with-docker

# The following detector IDs correspond to the "dog" and "cat" detectors.

EDGE_CONFIG=$(cat <<- EOM
local_inference_templates:
  default:
    enabled: true
  disabled:
    enabled: false

detectors:
  - detector_id: 'det_2UOxalD1gegjk4TnyLbtGggiJ8p'
    local_inference_template: 'disabled'

  - detector_id: 'det_2UOxao4HZyB9gv4ZVtwMOvdqgh9'
    local_inference_template: 'disabled'
EOM
)

export EDGE_CONFIG