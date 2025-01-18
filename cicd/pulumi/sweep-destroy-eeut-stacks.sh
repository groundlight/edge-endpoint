#!/bin/bash
# This script is run by the sweeper-eeut.yaml GitHub Actions workflow.
# It destroys all EEUT stacks that have expired.

set -e

# This function attempts to destroy a stack multiple times, and then removes it
# from Pulumi.  It's used to ensure that we can reliably destroy stacks that are
# marked to expire.
reliably_destroy_stack() {
  pulumi stack select $1
  pulumi destroy --yes || echo "Failed to destroy stack $1 on attempt 1"
  pulumi destroy --yes || echo "Failed to destroy stack $1 on attempt 2"
  pulumi destroy --yes
  pulumi stack rm $1 --yes
  echo "Stack $1 destroyed"
}

STACKS_JSON=$(pulumi stack ls --json)
# Stack output JSON looks like:
#[
#  {
#    # the pipeline YAML puts an expiration time (epochs) in the stack name
#    "name": "ee-cicd-1234-expires-1737243595",
#    "current": true,
#    "lastUpdate": "2025-01-18T00:58:02.000Z",
#    "updateInProgress": false,
#    "resourceCount": 0,
#    "url": "https://app.pulumi.com/something/ee-cicd/tmpdel"
#  }
#]
STACK_NAMES=$(echo "$STACKS_JSON" | jq -r '.[].name')
echo "Found $(echo "$STACK_NAMES" | wc -l) stacks"

for STACK_NAME in $STACK_NAMES; do
  if [[ $STACK_NAME == *"expires-"* ]]; then
    # This stack is marked to expire.  Check if the time has passed.
    EXPIRATION_TIME=$(echo "$STACK_NAME" | grep -oP 'expires-\K\d+')
    echo "EXPIRATION_TIME=${EXPIRATION_TIME}"
    if [[ $(date +%s) -gt $EXPIRATION_TIME ]]; then
      echo "Stack ${STACK_NAME} has expired.  Destroying..."
      reliably_destroy_stack $STACK_NAME
    else
      echo "Stack ${STACK_NAME} has not expired yet"
    fi
  else
    echo "Stack ${STACK_NAME} is not marked to expire"
  fi
done

echo "Sweep complete"