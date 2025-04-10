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

