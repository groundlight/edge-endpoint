#!/bin/bash
# This script is run by the sweeper-eeut.yaml GitHub Actions workflow.
# It destroys all EEUT stacks that have expired.

set -e

destroy_stack() {
  # We don't need to make this super robust (retrying a lot) because if it fails,
  # we'll try again next cron time.
  STACK_NAME=$1
  pulumi stack select $STACK_NAME
  pulumi destroy --yes
  pulumi stack rm $STACK_NAME --yes
  echo -e "Stack $STACK_NAME destroyed\n\n"
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
echo "Found $(echo "$STACK_NAMES" | wc -l) total stacks"
# We will filter out stacks that are currently being updated
# Because otherwise pulumi will just hang waiting its turn.
UPDATE_IN_PROGRESS_STACKS=$(echo "$STACKS_JSON" | jq -r '.[] | select(.updateInProgress == true) | .name')
echo "Found $(echo "$UPDATE_IN_PROGRESS_STACKS" | wc -l) stacks with updateInProgress: $UPDATE_IN_PROGRESS_STACKS"
NOT_IN_PROGRESS_STACKS=$(echo "$STACKS_JSON" | jq -r '.[] | select(.updateInProgress == false) | .name')
echo "Will process remaining $(echo "$NOT_IN_PROGRESS_STACKS" | wc -l) stacks"

set +e  # Plow ahead even if some stacks fail to destroy
for STACK_NAME in $NOT_IN_PROGRESS_STACKS; do
  if [[ $STACK_NAME == *"expires-"* ]]; then
    # This stack is marked to expire.  Check if the time has passed.
    EXPIRATION_TIME=$(echo "$STACK_NAME" | grep -oP 'expires-\K\d+')
    if [[ $(date +%s) -gt $EXPIRATION_TIME ]]; then
      echo "Stack ${STACK_NAME} has expired.  Destroying..."
      destroy_stack $STACK_NAME
    else
      echo "Stack ${STACK_NAME} has not expired yet"
    fi
  else
    echo "Stack ${STACK_NAME} is not marked to expire"
  fi
done

echo "Sweep complete"