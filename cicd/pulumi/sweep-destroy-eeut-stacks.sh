#!/bin/bash
# This script is run by the sweeper-eeut.yaml GitHub Actions workflow.
# It destroys all EEUT stacks that have expired.

set -e

destroy_stack() {
  # We don't need to make this super robust (retrying a lot) because if it fails,
  # we'll try again next cron time.
  STACK_NAME=$1
  pulumi stack select $STACK_NAME
  INSTANCE_ID=$(pulumi stack output eeut_instance_id 2>/dev/null)
  if [ -n "$INSTANCE_ID" ]; then
    # Note pulumi is too stupid to terminate an instance in the stopped state.
    # So we check for this manually.
    INSTANCE_STATE=$(aws ec2 describe-instances --instance-ids $INSTANCE_ID --query 'Reservations[*].Instances[*].State.Name' --output text)
    if [ "$INSTANCE_STATE" == "stopped" ]; then
      echo "Instance $INSTANCE_ID is stopped. Terminating..."
      aws ec2 terminate-instances --instance-ids $INSTANCE_ID || echo "Failed to terminate instance $INSTANCE_ID"
    fi
  fi
  pulumi destroy --yes  || echo "Failed to destroy stack $STACK_NAME"
  pulumi stack rm $STACK_NAME --yes || echo "Failed to remove stack $STACK_NAME"
  echo -e "Stack $STACK_NAME destroyed\n\n"
}

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
#  }, {...}
#]

STACKS_JSON=$(pulumi stack ls --json)
NUM_STACKS=$(echo "$STACKS_JSON" | jq -r '. | length')
echo "Found $NUM_STACKS total stacks"

for ((i=0; i<NUM_STACKS; i++)); do
  THIS_STACK=$(echo "$STACKS_JSON" | jq -r ".[$i]")
  STACK_NAME=$(echo "$THIS_STACK" | jq -r ".name")
  UPDATE_IN_PROGRESS=$(echo "$THIS_STACK" | jq -r ".updateInProgress")

  if [[ $UPDATE_IN_PROGRESS == "true" ]]; then
    # Pulumi will just hang waiting its turn if we try to work on this stack.
    echo "Stack ${STACK_NAME} is currently being updated. Skipping..."
    continue
  fi

  if [[ $STACK_NAME == *"expires-"* ]]; then
    # This stack is marked to expire. Check if the time has passed.
    EXPIRATION_TIME=$(echo "$STACK_NAME" | grep -oP 'expires-\K\d+')
    if [[ $(date +%s) -gt $EXPIRATION_TIME ]]; then
      echo "Stack ${STACK_NAME} has expired. Destroying..."
      echo "Stack has $(echo "$THIS_STACK" | jq -r ".resourceCount") resources"
      echo "Follow along online at $(echo "$THIS_STACK" | jq -r ".url")"
      destroy_stack $STACK_NAME
    else
      echo "Stack ${STACK_NAME} has not expired yet"
    fi
  else
    echo "Stack ${STACK_NAME} is not marked to expire"
  fi
done

echo "Sweep complete"