#!/bin/bash

# Usage:
# Execute the script using the following command:
# ./src/init-k8s-resources.sh [-e var1=value1 -e var2=value2 -f vals.env ...]
#
# Set up the Groundlight Edge Endpoint via Helm on a balena k3s cluster.
#
# Environment Variables:
# - KUBECTL_CMD: Path to kubectl command. Defaults to "kubectl".
# - GROUNDLIGHT_API_TOKEN: Required. The Groundlight API token.
# - GROUNDLIGHT_ENDPOINT: Optional. Override the upstream Groundlight endpoint.
# - EDGE_CONFIG: Optional. YAML contents for edge-config.
# - EDGE_ENDPOINT_VALUES: Optional. Comma-separated key=value pairs for helm --set flags.
# - RUN_EDGE_ENDPOINT: If unset or "0", edge-endpoint will not be deployed.

set -e

fail() {
    echo $1
    exit 1
}

#############################################################################################
# Environment variables:
# Figure out which environment variables were passed into the container and
# create a ConfigMap with them so we can pass them to the containers we're creating
# in Kubernetes
#############################################################################################

env_data=$(mktemp /tmp/env-data-XXXXXX)
edge_config_file=$(mktemp /tmp/edge-config-XXXXXX.yaml)

cleanup() {
    rm -f "$env_data"
    if [ -n "$edge_config_file" ]; then
        rm -f "$edge_config_file"
    fi
}
trap cleanup EXIT

# Run before cd so relative paths in -f args resolve correctly
"$(dirname $0)"/env-to-config-map.sh "$@" > $env_data

passed_in_api_token=$(grep -E '^GROUNDLIGHT_API_TOKEN:' $env_data | cut -d: -f2-)
if [ -n "$passed_in_api_token" ]; then
    export GROUNDLIGHT_API_TOKEN=$(echo $passed_in_api_token | tr -d ' "')
fi

if [ -z "$GROUNDLIGHT_API_TOKEN" ]; then
    echo "Error: GROUNDLIGHT_API_TOKEN is not set. Please set it in the environment or pass it as an argument."
    exit 1
fi

sed -i '/^GROUNDLIGHT_API_TOKEN:/d' $env_data

# Extract GROUNDLIGHT_ENDPOINT
passed_upstream_endpoint=$(grep -E '^GROUNDLIGHT_ENDPOINT:' $env_data | cut -d: -f2-)
if [ -n "$passed_upstream_endpoint" ]; then
    export GROUNDLIGHT_ENDPOINT=$(echo $passed_upstream_endpoint | tr -d ' "')
fi

GROUNDLIGHT_ENDPOINT_OPTION=""
if [ -n "${GROUNDLIGHT_ENDPOINT:-}" ]; then
    GROUNDLIGHT_ENDPOINT_OPTION="--set upstreamEndpoint=${GROUNDLIGHT_ENDPOINT}"
    sed -i '/^GROUNDLIGHT_ENDPOINT:/d' $env_data
fi

echo; echo
echo "Passthrough environment variables (sanitized):"
cat $env_data
echo; echo

# Extract RUN_EDGE_ENDPOINT
passed_run_edge_endpoint=$(grep -E '^RUN_EDGE_ENDPOINT:' $env_data | cut -d: -f2-)
if [ -n "$passed_run_edge_endpoint" ]; then
    export RUN_EDGE_ENDPOINT=$(echo $passed_run_edge_endpoint | tr -d ' "')
fi

# Extract EDGE_CONFIG
passed_edge_config=$(grep -E '^EDGE_CONFIG:' $env_data | cut -d: -f2-)
if [ -n "$passed_edge_config" ]; then
    export EDGE_CONFIG=$(echo "$passed_edge_config" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^"//' -e 's/"$//')
fi

# Extract EDGE_ENDPOINT_VALUES (comma-separated key=value pairs for helm --set flags)
passed_edge_endpoint_values=$(grep -E '^EDGE_ENDPOINT_VALUES:' $env_data | cut -d: -f2-)
if [ -n "$passed_edge_endpoint_values" ]; then
    export EDGE_ENDPOINT_VALUES=$(echo "$passed_edge_endpoint_values" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^"//' -e 's/"$//')
    sed -i '/^EDGE_ENDPOINT_VALUES:/d' $env_data
fi

# Build --set flags from EDGE_ENDPOINT_VALUES
# e.g. "imageTag=v1,inferenceTag=v2" -> "--set imageTag=v1 --set inferenceTag=v2"
EDGE_ENDPOINT_SET_OPTIONS=""
if [ -n "${EDGE_ENDPOINT_VALUES:-}" ]; then
    IFS=',' read -ra pairs <<< "$EDGE_ENDPOINT_VALUES"
    for pair in "${pairs[@]}"; do
        pair=$(echo "$pair" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
        if [ -n "$pair" ]; then
            EDGE_ENDPOINT_SET_OPTIONS="$EDGE_ENDPOINT_SET_OPTIONS --set $pair"
        fi
    done
fi

cd "$(dirname $0)"

#############################################################################################
# K3s initialization:
# Wait until the server pod is running and has created the config file
#############################################################################################

set +e
kubeconfig=${KUBECONFIG:-$HOME/.kube/config}
timeout=60
elapsed=0

echo "Waiting for kubeconfig to be created..."
while [ ! -f $kubeconfig ]; do
    sleep 1
    ((elapsed++))
    if [ "$elapsed" -ge "$timeout" ]; then
        fail "Error: Timed out after $timeout seconds waiting for ${kubeconfig}."
    fi
done
echo "done"

K=${KUBECTL_CMD:-"kubectl"}

elapsed=0

echo "Waiting for kubectl to connect to the k3s API server..."
while true; do
    $K get nodes >/dev/null 2>&1 && break
    sleep 1
    ((elapsed++))
    if [ "$elapsed" -ge "$timeout" ]; then
        fail "Error: Timed out after $timeout seconds waiting for the k3s API server."
    fi
done
echo "done"

set -e

#############################################################################################
# Edge endpoint:
# Install the edge endpoint from the published helm chart
#############################################################################################

if [ -z "${RUN_EDGE_ENDPOINT:-}" ] || [ "$RUN_EDGE_ENDPOINT" = "0" ]; then
    echo "RUN_EDGE_ENDPOINT is not set. Won't install the edge-endpoint."
    ee_deployment=$(helm ls -f edge-endpoint --no-headers -q -n default 2>/dev/null)
    if [ -n "$ee_deployment" ]; then
        echo "Deleting existing edge-endpoint deployment..."
        helm uninstall edge-endpoint -n default
    fi
else
    echo "RUN_EDGE_ENDPOINT is set. Starting edge endpoint."

    # Determine inference flavor from shared file written by server.sh (defaults to cpu)
    INFERENCE_FLAVOR="cpu"
    INFERENCE_FLAVOR_FILE="/shared/INFERENCE_FLAVOR"
    if [ -r "$INFERENCE_FLAVOR_FILE" ]; then
        INFERENCE_FLAVOR=$(cat "$INFERENCE_FLAVOR_FILE" | tr '[:upper:]' '[:lower:]' | tr -d ' \t\r\n')
    fi
    case "$INFERENCE_FLAVOR" in
        gpu|jetson|cpu) ;;
        *) INFERENCE_FLAVOR="cpu" ;;
    esac
    echo "Using inference flavor: $INFERENCE_FLAVOR"

    if [ -n "${EDGE_CONFIG:-}" ]; then
        echo "$EDGE_CONFIG" > $edge_config_file
        EDGE_CONFIG_OPTION="--set-file configFile=$edge_config_file"
        echo "EDGE_CONFIG is set. Created temporary config file at $edge_config_file"
    else
        echo "EDGE_CONFIG is not set. Won't create a temporary file for edge config."
        EDGE_CONFIG_OPTION=""
    fi

    helm repo add edge-endpoint https://code.groundlight.ai/edge-endpoint/
    helm repo update

    set +e
    if [ "$INFERENCE_FLAVOR" = "jetson" ]; then
        helm upgrade -i -n default edge-endpoint edge-endpoint/groundlight-edge-endpoint \
            --set groundlightApiToken="${GROUNDLIGHT_API_TOKEN}" \
            ${GROUNDLIGHT_ENDPOINT_OPTION} \
            ${EDGE_CONFIG_OPTION} \
            --set inferenceTag=${INFERENCE_FLAVOR} \
            ${EDGE_ENDPOINT_SET_OPTIONS}
        helm_exit_code=$?
    else
        helm upgrade -i -n default edge-endpoint edge-endpoint/groundlight-edge-endpoint \
            --set groundlightApiToken="${GROUNDLIGHT_API_TOKEN}" \
            ${GROUNDLIGHT_ENDPOINT_OPTION} \
            ${EDGE_CONFIG_OPTION} \
            --set inferenceFlavor=${INFERENCE_FLAVOR} \
            ${EDGE_ENDPOINT_SET_OPTIONS}
        helm_exit_code=$?
    fi
    set -e

    if [ $helm_exit_code -ne 0 ]; then
        echo "WARNING: Helm upgrade reported an error (exit code: $helm_exit_code)"
        echo "This may be due to pre-upgrade hook failures (e.g., BackoffLimitExceeded)."
        echo "The deployment may still succeed -- check pod status with: kubectl get pods -n edge"
    fi
fi

echo "Init complete."
