#!/bin/bash

# We need a separate build file to copy files into this directory because Docker refuses to 
# follow symlink "out of context"

cd "$(dirname "$0")"

# Function to clean up the copied files
cleanup() {
    rm -rf tmp
}
trap cleanup INT TERM EXIT HUP QUIT

mkdir -p tmp
(cd ../..; tar cf - --exclude "deploy/pure-docker" deploy) | (cd tmp; tar xf -)

docker build -t k3s-container .
