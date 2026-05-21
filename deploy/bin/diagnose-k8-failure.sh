#!/bin/bash
# Prints a bunch of diagnostics about the k8 status.
# Run in the CI/CD pipline on test failure.

if [ -z "$NAMESPACE" ]; then
    CONTEXT=""
else
    CONTEXT="-n $NAMESPACE"
fi

K="kubectl $CONTEXT"

set -x
set +e  # don't fail on errors - print all the diagnostics, even if some fail

df -h  # sometimes we run out of disk space

$K get all
$K describe deployment edge-endpoint
$K describe pod edge-endpoint
$K logs deployment/edge-endpoint -c edge-endpoint
$K logs deployment/edge-endpoint -c inference-model-updater

if [ -n "$NAMESPACE" ]; then
    HOOK_JOB="validate-api-token-$NAMESPACE"

    kubectl -n default get job "$HOOK_JOB"
    kubectl -n default describe job "$HOOK_JOB"
    kubectl -n default get pods -l job-name="$HOOK_JOB" -o wide
    kubectl -n default describe pods -l job-name="$HOOK_JOB"
    kubectl -n default logs job/"$HOOK_JOB" --all-containers=true
fi

exit 0
