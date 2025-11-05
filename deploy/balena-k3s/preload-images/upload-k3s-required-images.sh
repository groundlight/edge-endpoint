#!/bin/bash

cd "$(dirname $0)"

if [ $# -ne 1 ]; then echo "Usage: $(basename $0) <device-id>"; exit 1; fi

device_id=$1

for image in rancher/local-path-provisioner:v0.0.26 \
rancher/mirrored-coredns-coredns:1.10.1 \
rancher/mirrored-metrics-server:v0.7.0 \
rancher/mirrored-pause:3.6 \
rancher/klipper-helm:v0.8.3-build20240228
do
    upload-to-balena.sh $image $device_id
done
