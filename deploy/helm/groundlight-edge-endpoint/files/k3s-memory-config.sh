#!/bin/bash

# Set sensible kubelet eviction policies to prevent OOM crashes
# Configures memory thresholds that gracefully evict non-critical pods before system memory exhaustion.

echo "Configuring k3s memory limits with intelligent thresholds..."

# Check if this is a single-node k3s setup
NODE_COUNT=$(kubectl get nodes --no-headers | wc -l)
IS_K3S=$(ps aux | grep -q "[k]3s" && echo "true" || echo "false")

echo "Detected ${NODE_COUNT} nodes, k3s: ${IS_K3S}"

if [ "$NODE_COUNT" -gt 1 ]; then
  echo "Multi-node cluster detected (${NODE_COUNT} nodes). Skipping memory limits - let the cluster handle resource management."
  exit 0
fi

if [ "$IS_K3S" != "true" ]; then
  echo "Regular Kubernetes cluster detected. Skipping memory limits - using cluster-native resource management."
  exit 0
fi

echo "Single-node k3s detected. Applying memory limits to prevent OOM crashes..."

# Get total memory in KB
TOTAL_MEM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
TOTAL_MEM_BYTES=$((TOTAL_MEM_KB * 1024))
TOTAL_MEM_GB=$((TOTAL_MEM_BYTES / 1024 / 1024 / 1024))

echo "Detected ${TOTAL_MEM_GB}GB total memory"

# Define percentage thresholds and absolute minimums
HARD_PERCENT={{ .Values.k3sConfig.evictionHardPercent }}
SOFT_PERCENT={{ .Values.k3sConfig.evictionSoftPercent }}
HARD_MIN_GB={{ .Values.k3sConfig.evictionHardMinGB }}
SOFT_MIN_GB={{ .Values.k3sConfig.evictionSoftMinGB }}

# Calculate percentage-based thresholds in GB
HARD_PERCENT_GB=$((TOTAL_MEM_GB * HARD_PERCENT / 100))
SOFT_PERCENT_GB=$((TOTAL_MEM_GB * SOFT_PERCENT / 100))

# Use whichever is smaller: percentage or absolute minimum
if [ $HARD_MIN_GB -lt $HARD_PERCENT_GB ]; then
  HARD_MIN_GI=$(((HARD_MIN_GB * 1000000000 + 1073741824 - 1) / 1073741824))
  HARD_THRESHOLD="${HARD_MIN_GI}Gi"
  echo "Using hard threshold: ${HARD_MIN_GB}GB (${HARD_THRESHOLD}) - absolute minimum"
else
  HARD_THRESHOLD="${HARD_PERCENT}%"
  echo "Using hard threshold: ${HARD_THRESHOLD} (~${HARD_PERCENT_GB}GB)"
fi

if [ $SOFT_MIN_GB -lt $SOFT_PERCENT_GB ]; then
  SOFT_MIN_GI=$(((SOFT_MIN_GB * 1000000000 + 1073741824 - 1) / 1073741824))
  SOFT_THRESHOLD="${SOFT_MIN_GI}Gi"
  echo "Using soft threshold: ${SOFT_MIN_GB}GB (${SOFT_THRESHOLD}) - absolute minimum"
else
  SOFT_THRESHOLD="${SOFT_PERCENT}%"
  echo "Using soft threshold: ${SOFT_THRESHOLD} (~${SOFT_PERCENT_GB}GB)"
fi

# Add the eviction arguments to the k3s config file
CONFIG_FILE="/etc/rancher/k3s/config.yaml"
EVICTION_ARG_MARKER="# Groundlight Edge Endpoint memory management"

# Create directory if it doesn't exist
mkdir -p /etc/rancher/k3s

# Define our eviction arguments with marker comments
EVICTION_ARGS=$(cat << EOF
  - "eviction-hard=memory.available<${HARD_THRESHOLD}" $EVICTION_ARG_MARKER
  - "eviction-soft=memory.available<${SOFT_THRESHOLD}" $EVICTION_ARG_MARKER
  - "eviction-soft-grace-period=memory.available={{ .Values.k3sConfig.evictionGracePeriod }}" $EVICTION_ARG_MARKER
EOF
)

# If config file doesn't exist, create it with our args
if [ ! -f "$CONFIG_FILE" ]; then
    cat > "$CONFIG_FILE" << EOF
kubelet-arg:
$EVICTION_ARGS
EOF
    exit 0
fi

# Remove any existing eviction args (marked with our comment)
sed -i "/$EVICTION_ARG_MARKER/d" "$CONFIG_FILE"

# Check if kubelet-arg section exists
if grep -q "^kubelet-arg:" "$CONFIG_FILE"; then
    # Append our args to existing kubelet-arg section
    # Find the line number of kubelet-arg and insert after it
    awk -v eviction_args="$EVICTION_ARGS" '
    /^kubelet-arg:/ {
        print $0
        print eviction_args
        next
    }
    { print }
    ' "$CONFIG_FILE" > /tmp/updated_config && mv /tmp/updated_config "$CONFIG_FILE"
else
    # No kubelet-arg section exists, add it
    cat >> "$CONFIG_FILE" << EOF
kubelet-arg:
$EVICTION_ARGS
EOF
fi

# Report the results
echo "Generated k3s config:"
cat ${CONFIG_FILE}
echo "Restarting k3s..."
systemctl restart k3s
echo "k3s memory configuration completed"