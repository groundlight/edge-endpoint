#!/bin/bash

# Function to check if memory cgroups are actually working
check_cgroup() {
    if mount | grep -q "cgroup2"; then
        echo "Cgroup v2 is mounted."
        
        # Check if memory controller is available
        if [ -f "/sys/fs/cgroup/cgroup.controllers" ]; then
            if grep -q "memory" "/sys/fs/cgroup/cgroup.controllers"; then
                echo "Memory controller is available in cgroup v2."
                
                # Check if memory controller is enabled
                if [ -f "/sys/fs/cgroup/cgroup.subtree_control" ]; then
                    if grep -q "memory" "/sys/fs/cgroup/cgroup.subtree_control"; then
                        echo "Memory controller is enabled in cgroup v2."
                        return 0
                    else
                        echo "Memory controller is available but NOT ENABLED in cgroup v2."
                        echo "Try adding 'systemd.unified_cgroup_hierarchy=1' to kernel command line."
                        return 1
                    fi
                fi
            else
                echo "Memory controller is NOT AVAILABLE in cgroup v2."
                echo "You may need to add 'cgroup_memory=1 cgroup_enable=memory systemd.unified_cgroup_hierarchy=1' to kernel command line."
                return 1
            fi
        fi
        
        echo "Cgroup v2 is mounted but memory controller could not be verified."
        return 1
    elif mount | grep -q "cgroup/memory"; then
        # For cgroup v1, verify memory controller is actually functional
        if [ -f "/sys/fs/cgroup/memory/memory.limit_in_bytes" ]; then
            echo "Cgroup v1 (memory) is enabled and functional."
            return 0
        else
            echo "Cgroup v1 memory controller found but may not be functional."
            echo "You may need to add 'cgroup_memory=1 cgroup_enable=memory' to kernel command line."
            return 1
        fi
    else
        echo "No memory cgroup found."
        echo "You may need to add 'cgroup_memory=1 cgroup_enable=memory' to kernel command line."
        return 1
    fi
}

# Run the check
check_cgroup
CGROUP_STATUS=$?

# Final result
if [ $CGROUP_STATUS -eq 0 ]; then
    echo "Cgroup setup looks good."
    exit 0
else
    echo "Cgroup setup is NOT correct."
    exit 1
fi

