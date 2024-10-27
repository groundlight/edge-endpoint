#!/bin/bash

# Function to check if memory cgroups are available (v1 or v2)
check_cgroup() {
    if mount | grep -q "cgroup2"; then
        echo "Cgroup v2 is enabled."
        return 0
    elif mount | grep -q "cgroup/memory"; then
        echo "Cgroup v1 (memory) is enabled."
        return 0
    else
        echo "No memory cgroup found."
        return 1
    fi
}

# Function to check if required parameters are in /proc/cmdline
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

# Run the checks
check_cgroup
CGROUP_STATUS=$?

check_cmdline_params
PARAM_STATUS=$?

# Final result
if [ $CGROUP_STATUS -eq 0 ] && [ $PARAM_STATUS -eq 0 ]; then
    echo "Cgroup setup looks good."
    exit 0
else
    echo "Cgroup setup is NOT correct."
    exit 1
fi

