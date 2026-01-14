# Setting up the Edge Endpoint

The edge endpoint runs under Kubernetes, typically on a single-node cluster, which could be just a raspberry pi, or a powerful GPU server.  If you have a lot of detectors, it will scale out to a large multi-node cluster as well with zero changes except to the Kubernetes cluster setup. 

The instructions below are fairly opinionated, optimized for single-node cluster setup, using k3s, on an Ubuntu/Debian-based system.  If you want to set it up with a different flavor of kubernetes, that should work. Take the instructions below as a starting point and adjust as needed.

## Instructions for setting up a single-node Edge Endpoint

These are the steps to set up a single-node Edge Endpoint:

1. [Set up a local Kubernetes cluster with k3s](#setting-up-single-node-kubernetes-with-k3s).
2. [Set your Groundlight API token](#set-the-groundlight-api-token).
3. [Set up to use the Helm package manager](#setting-up-for-helm).
4. [Install the Edge Endpoint with Helm](#installing-the-edge-endpoint-with-helm).
5. [Confirm that the Edge Endpoint is running](#verifying-the-installation).

If you follow these instructions and something isn't working, please check the [troubleshooting section](#troubleshooting-deployments) for help.

### TL;DR - No fluff, just bash commands

This is the quick version of the instructions above.  On a fresh system with no other customization, you can run the following commands to set up the Edge Endpoint.

Before starting, get a Groundlight API token from the Groundlight web app and set it as an environment variable:

```shell
export GROUNDLIGHT_API_TOKEN="api_xxxxxx"
```

Then, run the following commands to set up the Edge Endpoint:

For GPU-based systems:

```shell
curl -fsSL https://raw.githubusercontent.com/groundlight/edge-endpoint/refs/heads/main/deploy/bin/install-k3s.sh | bash -s gpu
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
helm upgrade -i -n default edge-endpoint edge-endpoint/groundlight-edge-endpoint \
  --set groundlightApiToken="${GROUNDLIGHT_API_TOKEN}"
```

For CPU-based systems:

```shell
curl -fsSL https://raw.githubusercontent.com/groundlight/edge-endpoint/refs/heads/main/deploy/bin/install-k3s.sh | bash -s cpu
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
helm upgrade -i -n default edge-endpoint edge-endpoint/groundlight-edge-endpoint \
  --set groundlightApiToken="${GROUNDLIGHT_API_TOKEN}" \
  --set inferenceFlavor=cpu
```

For Jetson Orin-based systems (experimental):

```shell
curl -fsSL https://raw.githubusercontent.com/groundlight/edge-endpoint/refs/heads/main/deploy/bin/install-k3s.sh | bash -s jetson
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
helm upgrade -i -n default edge-endpoint edge-endpoint/groundlight-edge-endpoint \
  --set groundlightApiToken="${GROUNDLIGHT_API_TOKEN}" \
  --set inferenceTag="jetson"
```

You're done. You can skip down to [Verifying the Installation](#verifying-the-installation) to confirm that the Edge Endpoint is running.

### Setting up Single-Node Kubernetes with k3s

If you don't have [k3s](https://docs.k3s.io/) installed, there is a script which can install it depending on whether you have a NVidia GPU or not.  If you don't set up a GPU, the models will run on the CPU, but be somewhat slower.

```shell
# For GPU inference
curl -fsSL -O https://raw.githubusercontent.com/groundlight/edge-endpoint/refs/heads/main/deploy/bin/install-k3s.sh 
bash ./install-k3s.sh gpu
```

```shell
# For CPU inference
curl -fsSL -O https://raw.githubusercontent.com/groundlight/edge-endpoint/refs/heads/main/deploy/bin/install-k3s.sh 
bash ./install-k3s.sh cpu
```

This script will install the k3s Kubernetes distribution on your machine.  If you use the `gpu` argument, the script will also install the  NVIDIA GPU plugin for Kubernetes. It will also install the [Helm](https://helm.sh) package manager, which is used to deploy the edge-endpoint, and the Linux utilities `curl` and `jq`, if you don't already have them.

### Set the Groundlight API Token

To enable the Edge Endpoint to communicate with the Groundlight service, you need to get a
Groundlight API token. You can create one on [this page](https://dashboard.groundlight.ai/reef/my-account/api-tokens) and set it as an environment variable.

```shell
export GROUNDLIGHT_API_TOKEN="api_xxxxxx"
```

> [!NOTE]
> Your Groundlight account needs to be enabled to support the Edge Endpoint. If you don't have 
> access to the Edge Endpoint, please contact Groundlight support (support@groundlight.ai).

### Setting up for Helm

[Helm](https://helm.sh/) is a package manager for Kubernetes. Groundlight distributes the edge endpoint via a "Helm Chart."

If you've just installed k3s with the setup script above, you should have Helm installed and the edge-endpoint chart repository added. In this case, you can skip to step 3.  

If you're setting up Helm on a machine that already has k3s (or another Kubernetes environment) installed, do all three steps to get started.

####  Step 1: Install Helm

Run the Helm install script (as described [here](https://helm.sh/docs/intro/install/)):

```shell
curl -fsSL -o /tmp/get_helm.sh https://raw.githubusercontent.com/helm/helm/master/scripts/get-helm-3
bash /tmp/get_helm.sh
```


#### Step 2: Add the Groundlight Helm repository
```
helm repo add edge-endpoint https://code.groundlight.ai/edge-endpoint/
helm repo update
```

#### Step 3: Point Helm to the k3s cluster

If you installed k3s with the script above, it should have created a kubeconfig file in `/etc/rancher/k3s/k3s.yaml`.  This is the file that Helm will use to connect to your k3s cluster.

If you're running with k3s and you haven't created a kubeconfig file in your home directory, you need to tell Helm to use the one that k3s created.  You can do this by setting the `KUBECONFIG` environment variable:

```shell 
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
```

You probably want to set this in your `.bashrc` or `.zshrc` file so you don't have to set it every time you open a new terminal.


### Installing the Edge Endpoint with Helm

For a simple, default installation, you can run the following command:

```shell
helm upgrade -i -n default edge-endpoint edge-endpoint/groundlight-edge-endpoint \
  --set groundlightApiToken="${GROUNDLIGHT_API_TOKEN}"
```

This will install the Edge Endpoint doing GPU-based inference in the `edge` namespace in your k3s cluster and expose it on port 30101 on your local node. Helm will keep a history of the installation in the `default` namespace (signified by the `-n default` flag).

To change values that you've customized after you've installed the Edge Endpoint or to install an updated chart, use the `helm upgrade` command. For example, to change the `groundlightApiToken` value, you can run:

```shell
helm upgrade -i -n default edge-endpoint edge-endpoint/groundlight-edge-endpoint \
  --set groundlightApiToken="<new groundlight api token>"
```

#### Variation: Custom Edge Endpoint Configuration

You might want to customize the edge config file to include the detector ID's you want to run. See [the guide to configuring detectors](/CONFIGURING-DETECTORS.md) for more information. Adding detector ID's to the config file will cause inference pods to be initialized automatically for each detector and provides you finer-grained control over each detector's behavior. Even if detectors aren't configured in the config file, edge inference will be set up for each detector ID for which the Groundlight service receives requests (note that it takes some time for each inference pod to become available for the first time).

You can find an example edge config file here: [edge-config.yaml](https://github.com/groundlight/edge-endpoint/blob/clone-free-install/configs/edge-config.yaml). The easiest path is to download that file and modify it to your needs.

To use a custom edge config file, set the `configFile` Helm value to the path of the file:

```shell
helm upgrade -i -n default edge-endpoint edge-endpoint/groundlight-edge-endpoint \
  --set groundlightApiToken="${GROUNDLIGHT_API_TOKEN}" --set-file configFile=/path/to/your/edge-config.yaml
```
#### Variation: CPU Mode Inference

If the system you're running on doesn't have a GPU, you can run the Edge Endpoint in CPU mode. To do this, set the `inferenceFlavor` Helm value to `cpu`:

```shell
helm upgrade -i -n default edge-endpoint edge-endpoint/groundlight-edge-endpoint \
  --set groundlightApiToken="${GROUNDLIGHT_API_TOKEN}" \
  --set inferenceFlavor=cpu
```

#### Variation: Disable the network healer

The chart includes a small "network healer" deployment that restarts k3s when cluster DNS (CoreDNS) is unhealthy. This is most useful on devices where the host IP can change (for example laptops moving between networks), which can leave CoreDNS broken until k3s is restarted. It is enabled by default.

To disable it, set `networkHealer.enabled=false`:

```shell
helm upgrade -i -n default edge-endpoint edge-endpoint/groundlight-edge-endpoint \
  --set groundlightApiToken="${GROUNDLIGHT_API_TOKEN}" \
  --set networkHealer.enabled=false
```

#### Variation: Further Customization

The Helm chart supports various configuration options which can be set using `--set` flags. For the full list, with default values and documentation, see the [values.yaml](helm/groundlight-edge-endpoint/values.yaml) file.

If you want to customize a number of values, you can create a `values.yaml` file with your custom values and pass it to Helm:

```shell
helm upgrade -i -n default edge-endpoint edge-endpoint/groundlight-edge-endpoint -f /path/to/your/values.yaml
```

### Verifying the Installation

After installation, verify your pods are running:

```bash
kubectl get pods -n edge
```

You should see output similar to:

```
NAME                             READY   STATUS    RESTARTS   AGE
edge-endpoint-6d7b9c4b59-wdp8f   2/2     Running   0          2m
```

Now you can access the Edge Endpoint at `http://localhost:30101`. For use with the Groundlight SDK, you can set the `GROUNDLIGHT_ENDPOINT` environment variable to `http://localhost:30101`.

### Uninstalling Edge Endpoint

To remove the Edge Endpoint deployed with Helm:

```bash
helm uninstall -n default edge-endpoint
```

## Legacy Instructions

> [!NOTE]
> The older setup mechanism with `setup-ee.sh` is still available, but we recommend using Helm for
> new installations and converting existing installations to Helm when possible. See the section
> [Converting from setup-ee.sh to Helm](#converting-from-setup-eesh-to-helm) for instructions on
> how to do this.

If you haven't yet installed the k3s Kubernetes distribution, follow the steps in the [Setting up Single-Node Kubernetes with k3s](#setting-up-single-node-kubernetes-with-k3s) section.

You might want to customize the [edge config file](../configs/edge-config.yaml) to include the detector ID's you want to run. See [the guide to configuring detectors](/CONFIGURING-DETECTORS.md) for more information. Adding detector ID's to the config file will cause inference pods to be initialized automatically for each detector and provides you finer-grained control over each detector's behavior. Even if detectors aren't configured in the config file, edge inference will be set up for each detector ID for which the Groundlight service receives requests (note that it takes some time for each inference pod to become available for the first time).

Before installing the edge-endpoint, you need to create/specify the namespace for the deployment. If you're creating a new one, run:

```bash
kubectl create namespace "your-namespace-name"
```

Whether you created a new namespace or are using an existing one, set the DEPLOYMENT_NAMESPACE environment variable:
```bash
export DEPLOYMENT_NAMESPACE="your-namespace-name"
```

Some other environment variables should also be set. You'll need to have created
a Groundlight API token in the [Groundlight web app](https://app.groundlight.ai/reef/my-account/api-tokens).
```bash
# Set your API token
export GROUNDLIGHT_API_TOKEN="api_xxxxxx"

# Choose an inference flavor, either CPU or (default) GPU.
# Note that appropriate setup for GPU will need to be done separately.
export INFERENCE_FLAVOR="CPU"
# OR
export INFERENCE_FLAVOR="GPU"
```

You'll also need to configure your AWS credentials using `aws configure` to include credentials that have permissions to pull from the appropriate ECR location (if you don't already have the AWS CLI installed, refer to the instructions [here](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)).

To install the edge-endpoint, run:
```shell
./deploy/bin/setup-ee.sh
```

This will create the edge-endpoint deployment, which is both the SDK proxy and coordination service. After a short while, you should be able to see something like this if you run `kubectl get pods -n "your-namespace-name"`:

```
NAME                                    READY   STATUS    RESTARTS   AGE
edge-endpoint-594d645588-5mf28          2/2     Running   0          4s
```

If you configured detectors in the [edge config file](/configs/edge-config.yaml), you should also see `inferencemodel` pod(s) for each detector.
By default, there will be two `inferencemodel` pods per detector (one for primary inference and one for out of domain detection), e.g.:

```
NAME                                                                        READY   STATUS    RESTARTS   AGE
edge-endpoint-594d645588-5mf28                                              2/2     Running   0          4s
inferencemodel-primary-det-3jemxiunjuekdjzbuxavuevw15k-5d8b454bcb-xqf8m     1/1     Running   0          2s
inferencemodel-oodd-det-3jemxiunjuekdjzbuxavuevw15k-5d8b454bcb-xqf8m        1/1     Running   0          2s
```

In minimal mode, there should only be one `inferencemodel` pod per detector (only primary inference, no separate OODD pod). 

We currently have a hard-coded docker image from ECR in the [edge-endpoint](/edge-endpoint/deploy/k3s/edge_deployment.yaml)
deployment. If you want to make modifications to the edge endpoint code and push a different
image to ECR see [Pushing/Pulling Images from ECR](#pushingpulling-images-from-elastic-container-registry-ecr).

### Converting from `setup-ee.sh` to Helm

If you have an existing edge-endpoint deployment set up with `setup-ee.sh` and want to convert it to Helm, you can follow these steps:

1. Uninstall the existing edge-endpoint deployment:
```shell
DEPLOYMENT_NAMESPACE=<namespace-you-deployed-to> ./deploy/bin/delete-old-deployment.sh
```
2. Follow the instructions in the [Setting up for Helm](#setting-up-for-helm) section to set up Helm.
3. That's it

## Troubleshooting Deployments

Here are some common issues you might encounter when deploying the edge endpoint and how to resolve them. If you have an issue that's not listed here, please contact Groundlight support at [support@groundlight.ai](mailto:support@groundlight.ai) for more assistence.

### Helm deployment fails with `validate-api-token` error

If you see an error like this when running the Helm install command:
```
Error: failed pre-install: 1 error occurred:
        * job validate-api-token-edge failed: BackoffLimitExceeded
```
it means that the API token you provided is not giving access.

There are two possible reasons for this:
1. The API token is invalid. Check the value you're providing and make sure it maps to a valid API token in the Groundlight web app.
2. Your account does not have permission to use edge services. Not all plans enable edge inference. To find out more and get your account enabled, contact Groundlight support at [support@groundlight.ai](mailto:support@groundlight.ai).

To diagnose which of these is the issue (or if it's something else entirely), you can check the logs of the `validate-api-token-edge` job:

```shell
kubectl logs -n default job/validate-api-token-edge
```

(If you're installing into a different namespace, replace `edge` in the job name with the name of your namespace.)

This will show you the error returned by the Groundlight cloud service.

After resolving this issue, you need to reset the Helm release to get back to a clean state. You can do this by running:

```shell
helm uninstall -n default edge-endpoint --keep-history
```

Then, re-run the Helm install command.

### Helm deployment fails with `namespaces "edge" not found`.

This happens when there was an initial failure in the Helm install command and the namespace was not created. 

To fix this, reset the Helm release to get back to a clean state. You can do this by running:

```shell
helm uninstall -n default edge-endpoint --keep-history
```

Then, re-run the Helm install command.

### Pods with `ImagePullBackOff` Status

Check the `refresh_creds` cron job to see if it's running. If it's not, you may need to re-run [refresh-ecr-login.sh](/deploy/bin/refresh-ecr-login.sh) to update the credentials used by docker/k3s to pull images from ECR.  If the script is running but failing, this indicates that the stored AWS credentials (in secret `aws-credentials`) are invalid or not authorized to pull algorithm images from ECR.

```
kubectl logs -n <YOUR-NAMESPACE> -l app=refresh_creds
```

### Changing IP Address Causes DNS Failures and Other Problems
When the IP address of the machine you're using to run edge-endpoint changes, it creates an inconsistent environment for the
k3s system (which doesn't automatically update itself to reflect the change). The most obvious symptom of this is that DNS
address resolution stops working.

If this happens, there's a script to reset the address in k3s and restart the components that need restarting.

From the edge-endpoint directory, you can run:
```
deploy/bin/ip-changed.sh
```
If you're in another directory, adjust the path appropriately.

When the script is complete (it should take roughly 15 seconds), address resolution and other Kubernetes features should
be back online.

If you're running edge-endpoint on a transportable device, such as a laptop, you should run `ip-changed.sh` every time you switch
access points.

### EC2 Networking Setup Creates a Rule That Causes DNS Failures and Other Problems

Another source of DNS/Kubernetes service problems is the netplan setup that some EC2 nodes use. I don't know why this
happens on some nodes but not others, but it's easy to see if this is the problem. 

To check, run `ip rule`. If the output has an item with rule 1000 like the following, you have this issue:
```
0:      from 10.45.0.177 lookup 1000
```

to resolve this, simply run the script `deploy/bin/fix-g4-routing.sh`.

The issue should be permanently resolved at this point. You shouldn't need to run the script again on that node, 
even after rebooting.
## Pushing/Pulling Images from Elastic Container Registry (ECR)

We currently have a hard-coded docker image in our k3s deployment, which is not ideal.
If you're testing things locally and want to use a different docker image, you can do so
by first creating a docker image locally, pushing it to ECR, retrieving the image ID and
then using that ID in the [edge_deployment](k3s/edge_deployment/edge_deployment.yaml) file.

Follow the following steps:

```shell
# Build and push image to ECR
> ./deploy/bin/build-push-edge-endpoint-image.sh
```
