#!/bin/bash

# Use this script to delete deployments that were made before we switched to helm

set -e
K=${KUBECTL_CMD:-"kubectl"}

DEPLOYMENT_NAMESPACE=${DEPLOYMENT_NAMESPACE:-$($K config view -o json | jq -r '.contexts[] | select(.name == "'$($K config current-context)'") | .context.namespace // "default"')}

NS=$($K get namespace $DEPLOYMENT_NAMESPACE --ignore-not-found -o name)
if [ -z "$NS" ]; then
    echo "Namespace $DEPLOYMENT_NAMESPACE does not exist"
    exit 1
fi

# Update K to include the deployment namespace
K="$K -n $DEPLOYMENT_NAMESPACE"

# Check to see if this namespace was installed using helm and, if so, tell the user
# to use helm to clear the deployment
HELM_RELEASE=$($K get deployment edge-endpoint -o json --ignore-not-found | jq -r '.metadata.annotations."meta.helm.sh/release-name"|select(.)')
if [ -n "$HELM_RELEASE" ]; then
    echo "Namespace $DEPLOYMENT_NAMESPACE was installed using helm. Please use helm to delete the deployment:"
    echo "   helm uninstall $HELM_RELEASE"
    exit 1
fi

# Delete the deployments, jobs, and cronjob
$K delete deployment edge-endpoint --ignore-not-found
$K get deployment -o name | grep /inferencemodel- | xargs -I {} $K delete {}
$K delete cronjob refresh-creds --ignore-not-found
$K delete job warmup-inference-model --ignore-not-found

# Delete the services
$K delete service edge-endpoint-service --ignore-not-found
$K get service -o name | grep /inference-service- | xargs -I {} $K delete {}

# Delete secrets and configmaps
$K delete secret aws-credentials --ignore-not-found
$K delete secret registry-credentials --ignore-not-found

$K delete configmap edge-config --ignore-not-found
$K delete configmap inference-deployment-template --ignore-not-found
$K delete configmap kubernetes-namespace --ignore-not-found
$K delete configmap setup-db --ignore-not-found

# Delete the PVC and its associated PV
PVC=$($K get pvc edge-endpoint-pvc -o name --ignore-not-found)
if [ -n "$PVC" ]; then
    PV=$($K get pvc edge-endpoint-pvc -o json | jq -r .spec.volumeName)
    $K delete $PVC
    $K delete pv $PV --ignore-not-found
fi

# Delete account and role
$K delete serviceaccount edge-endpoint-service-account --ignore-not-found
$K delete rolebinding edge-endpoint-role-binding --ignore-not-found
$K delete role limited-access-role --ignore-not-found

# Delete the namespace, if it's empty and not the default namespace
# Note that we check for common resources that we would care about, but not everything
if [ "$DEPLOYMENT_NAMESPACE" != "default" ]; then
    set +e
    CONTENTS=$($K get all,secrets,cm -o name --ignore-not-found | grep -v kube-root-ca)
    set -e
    if [ -z "$CONTENTS" ]; then
        echo "Deleting namespace $DEPLOYMENT_NAMESPACE since its now empty"
        $K delete namespace $DEPLOYMENT_NAMESPACE
    else
        echo "Namespace ${DEPLOYMENT_NAMESPACE} not empty, not deleting"
    fi
else
    echo "Not deleting default namespace"
fi
