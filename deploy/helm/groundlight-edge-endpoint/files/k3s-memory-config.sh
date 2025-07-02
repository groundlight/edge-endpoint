#!/bin/bash

# Set sensible kubelet eviction policies to prevent OOM crashes
# Configures memory thresholds that gracefully evict non-critical pods before system memory exhaustion.

echo "Configuring k3s memory limits with intelligent thresholds..."

# Check if this is a single-node k3s setup. We only want to set eviction policies on single-node k3s setups.
NODE_COUNT=$(kubectl get nodes --no-headers | wc -l)
IS_K3S=$(kubectl version 2>/dev/null | grep -q "k3s" && echo "true" || echo "false")

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

# Get total memory in KB and convert to GB
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

# Use whichever is smaller: percentage or absolute minimum. Convert from GB to Gi.
if [ $HARD_MIN_GB -lt $HARD_PERCENT_GB ]; then
  HARD_MIN_GI=$(((HARD_MIN_GB * 1000000000 + 1073741824 - 1) / 1073741824)) # round up
  HARD_THRESHOLD="${HARD_MIN_GI}Gi"
  echo "Using hard threshold: ${HARD_MIN_GB}GB (${HARD_THRESHOLD}) - absolute minimum"
else
  HARD_THRESHOLD="${HARD_PERCENT}%"
  echo "Using hard threshold: ${HARD_THRESHOLD} (~${HARD_PERCENT_GB}GB)"
fi

if [ $SOFT_MIN_GB -lt $SOFT_PERCENT_GB ]; then
  SOFT_MIN_GI=$(((SOFT_MIN_GB * 1000000000 + 1073741824 - 1) / 1073741824)) # round up
  SOFT_THRESHOLD="${SOFT_MIN_GI}Gi"
  echo "Using soft threshold: ${SOFT_MIN_GB}GB (${SOFT_THRESHOLD}) - absolute minimum"
else
  SOFT_THRESHOLD="${SOFT_PERCENT}%"
  echo "Using soft threshold: ${SOFT_THRESHOLD} (~${SOFT_PERCENT_GB}GB)"
fi

# Configure k3s, preserve user-defined config (if any)
mkdir -p /etc/rancher/k3s
CONFIG_FILE="/etc/rancher/k3s/config.yaml"
MARKER="# Groundlight Edge Endpoint memory management"

# Remove old eviction settings
if [ -f "$CONFIG_FILE" ]; then
  sed -i "/$MARKER/d" "$CONFIG_FILE"
fi

# Ensure kubelet-arg section exists
if [ ! -f "$CONFIG_FILE" ] || ! grep -q "^kubelet-arg:" "$CONFIG_FILE"; then
  echo "kubelet-arg:" >> "$CONFIG_FILE"
fi

# Insert eviction settings right after kubelet-arg: line
sed -i "/^kubelet-arg:/a\\
  - \"eviction-hard=memory.available<${HARD_THRESHOLD}\" $MARKER\\
  - \"eviction-soft=memory.available<${SOFT_THRESHOLD}\" $MARKER\\
  - \"eviction-soft-grace-period=memory.available=10s\" $MARKER" "$CONFIG_FILE"

# Report the results
echo "Generated k3s config:"
cat ${CONFIG_FILE}
echo "Restarting k3s..."
systemctl restart k3s
echo "k3s memory configuration completed"