#!/bin/bash
# Safety-net cleanup for orphaned EEUT (edge-endpoint-under-test) instances.
#
# WHY THIS EXISTS
# ---------------
# The G4-end-to-end CI job creates a Pulumi stack named
#   ee-cicd-<github_run_id>-expires-<unix_epoch>
# and a g4dn EC2 instance tagged
#   Name=eeut-ee-cicd-<github_run_id>-expires-<unix_epoch>
# meant to live ~60 minutes. Normally sweep-destroy-eeut-stacks.sh tears it down
# after the embedded expiry by walking `pulumi stack ls`.
#
# But that sweeper is entirely Pulumi-stack-driven, and an instance can outlive
# its stack:
#   - `pulumi up` is interrupted (PR cancel-in-progress, or a hard failure) after
#     AWS has launched the instance but before Pulumi checkpoints it into state.
#   - The instance now exists in AWS but is NOT tracked by the stack.
#   - When the sweeper later processes the expired stack, `pulumi stack output
#     eeut_instance_id` is empty and `pulumi destroy` "succeeds" against empty
#     state, so `pulumi stack rm` deletes the stack -- abandoning the live
#     instance. From then on `pulumi stack ls` shows nothing, so the stack
#     sweeper is permanently blind to it. (A changed Pulumi org/project/backend
#     causes the same blind spot for very old stacks.)
#
# This reaper closes that gap: it works directly from the EC2 Name tag,
# independent of Pulumi state, reading the expiry straight out of the tag. It is
# a complement to -- not a replacement for -- the stack sweeper: the stack
# sweeper still owns Pulumi stack lifecycle for tracked stacks; this owns the
# AWS-side safety net for orphans. There is nothing to clean up on the Pulumi
# side for these orphans, because by definition their stack is already gone.
#
# Set DRY_RUN=1 to log what would be terminated without terminating anything.

set -euo pipefail

REGION="${AWS_REGION:-us-west-2}"
NOW=$(date +%s)
DRY_RUN="${DRY_RUN:-0}"

echo "Reaping orphaned eeut-* instances in ${REGION} (now=${NOW}, dry_run=${DRY_RUN})"

# Find non-terminated instances named like an EEUT test box. Other instances
# (gha-runner, dev boxes, EKS nodes, ...) don't match eeut-* and are never
# touched. We additionally require an `expires-<epoch>` token below, so anything
# without a parseable expiry is left alone as a second safeguard.
INSTANCES_JSON=$(aws ec2 describe-instances \
  --region "${REGION}" \
  --filters \
    "Name=tag:Name,Values=eeut-*" \
    "Name=instance-state-name,Values=pending,running,stopping,stopped" \
  --query 'Reservations[].Instances[].{Id:InstanceId, Name:Tags[?Key==`Name`]|[0].Value, State:State.Name}' \
  --output json)

NUM=$(echo "${INSTANCES_JSON}" | jq 'length')
echo "Found ${NUM} live eeut-* instance(s)"

REAPED=0
while IFS= read -r row; do
  [ -z "${row}" ] && continue
  ID=$(echo "${row}" | jq -r '.Id')
  NAME=$(echo "${row}" | jq -r '.Name')
  STATE=$(echo "${row}" | jq -r '.State')

  # Pull the expiry epoch out of the name: ...-expires-<digits>
  EXPIRES=$(echo "${NAME}" | grep -oE 'expires-[0-9]+' | grep -oE '[0-9]+' || true)
  if [ -z "${EXPIRES}" ]; then
    echo "  SKIP ${ID} (${NAME}): no expires-<epoch> in name"
    continue
  fi

  if [ "${NOW}" -le "${EXPIRES}" ]; then
    REMAIN=$(( (EXPIRES - NOW) / 60 ))
    echo "  KEEP ${ID} (${NAME}): not expired yet (~${REMAIN} min remaining, state=${STATE})"
    continue
  fi

  OVERDUE=$(( (NOW - EXPIRES) / 60 ))
  echo "  EXPIRED ${ID} (${NAME}): ${OVERDUE} min past expiry (state=${STATE})"
  if [ "${DRY_RUN}" = "1" ]; then
    echo "    [dry-run] would terminate ${ID}"
  else
    if aws ec2 terminate-instances --region "${REGION}" --instance-ids "${ID}" >/dev/null; then
      echo "    terminated ${ID}"
    else
      echo "    FAILED to terminate ${ID}"
    fi
  fi
  REAPED=$(( REAPED + 1 ))
done < <(echo "${INSTANCES_JSON}" | jq -c '.[]')

echo "Reaper complete: ${REAPED} expired instance(s) processed"
