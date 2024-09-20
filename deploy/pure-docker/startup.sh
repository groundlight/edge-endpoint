#!/bin/sh

# Start the k3s server and then give it the config that we want. 

# Use the environment to tell what detectors we want.

/bin/k3s server > /tmp/k3s-server.log 2>&1 & # TODO - don't let this log expand forever

sleep 5 # Wait for the server to come up

# Start the edge inference app
/opt/groundlight/deploy/bin/cluster_setup.sh

wait
