#!/bin/bash

set -ex

if [ $# -ne 2 ]; then echo "Usage: $(basename $0) <docker-image> <device-id>"; exit 1; fi

tmpdir=/tmp

image=$1
device_id=$2

base=$(echo $image | sed 's%^.*/\([^/]*\)$%\1%' | sed 's/:/-/g').tar
file=${tmpdir}/$base

docker pull ${image}
docker save ${image} -o ${file}

preload_dir=$(echo "ls -d /mnt/data/docker/volumes/*_k3s-server/_data/agent; exit" | balena device ssh ${device_id} | tail -1)/images
# preload_dir=/home/root

echo "if [ ! -d ${preload_dir} ]; then mkdir ${preload_dir}; fi; exit" | balena device ssh ${device_id}

(echo "cat > /tmp/${base}.b64 <<EOF"; base64 ${file}; echo "EOF"; echo "base64 -d /tmp/${base}.b64 > ${preload_dir}/$base"; echo "rm /tmp/${base}.b64; exit") | \
    balena device ssh ${device_id}
