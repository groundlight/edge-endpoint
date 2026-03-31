#!/bin/bash
set -e

NS=$(cat /var/run/secrets/kubernetes.io/serviceaccount/namespace)

echo "Checking for warmup-inference-model job..."
if kubectl get job warmup-inference-model -n "$NS" &>/dev/null; then
    echo "Waiting for warmup-inference-model to complete..."
    kubectl wait --for=condition=complete job/warmup-inference-model -n "$NS" --timeout=1800s \
        || echo "Wait timed out or job failed, proceeding anyway."
else
    echo "Warmup job not found, proceeding."
fi
