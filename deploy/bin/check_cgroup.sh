#!/bin/bash

# Function to check if memory cgroup is mounted
check_memory_cgroup_mounted() {
    if mount | grep -q "cgroup/memory"; then
        echo "Memory cgroup is mounted."
        return 0
    else
        echo "Memory cgroup is NOT mounted."
        return 1
    fi
}

# Function to check kernel cmdline parameters for cgroup settings
check_cmdline_params() {
    CMDLINE=$(cat /proc/cmdline)
    if echo "$CMDLINE" | grep -q "cgroup_memory=1" && echo "$CMDLINE" | grep -q "cgroup_enable=memory"; then
        echo "Required cgroup parameters are present in /proc/cmdline."
        return 0
    else
        echo "Required cgroup parameters are MISSING from /proc/cmdline."
        return 1
    fi
}

# Run both checks and determine overall status
check_memory_cgroup_mounted
MOUNT_STATUS=$?

check_cmdline_params
PARAM_STATUS=$?

if [ $MOUNT_STATUS -eq 0 ] && [ $PARAM_STATUS -eq 0 ]; then
    echo "Memory cgroup is properly enabled."
    exit 0
else
    echo "Memory cgroup is NOT properly enabled."
    exit 1
fi

