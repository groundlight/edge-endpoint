#!/bin/bash

container=myk3s
configfile=/tmp/k3s-docker.yaml

docker exec -i ${container} cat /etc/rancher/k3s/k3s.yaml | sed 's/:6443/:7443/' > ${configfile}

export KUBECONFIG=${configfile}

