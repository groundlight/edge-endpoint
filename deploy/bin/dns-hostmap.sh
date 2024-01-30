#!/bin/bash
# Adds a DNS hostmap entry for app.dev.groundlight.ai to your ingress

set -e

fail() {
    echo $1
    exit 1
}

K="kubectl"
which $K || fail "Could not find kubectl"

MSG_ACCUMULATOR=""

# Function to map ingress to a specific name on local machine
map_ingress_to_local() {
    URL=$1
    INGRESS=$2

    # First figure out the IP address
    ELB_NAME=$($K get ing | grep $INGRESS | awk '{print $4}')
    ELB_IP=$(nslookup $ELB_NAME | grep answer -A 2 | tail -1 |  awk '{print $2}')
    echo $ELB_IP  # make sure this is not blank.  It can take several minutes to set up

    # Now update the /etc/hosts file
    grep -v $URL /etc/hosts | sudo tee /etc/hosts
    echo "$ELB_IP   $URL" | sudo tee -a /etc/hosts

    MSG_ACCUMULATOR="${MSG_ACCUMULATOR}\n$ELB_IP   $URL" 
}

# Call the function for each URL and ingress
map_ingress_to_local "edge.groundlight.ai" "edge-api"

echo -e "\n\nUpdated local /etc/hosts.  To update another machine, add these lines to its /etc/hosts:"
echo -e $MSG_ACCUMULATOR

