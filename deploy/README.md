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
> access to the Edge Endpoint, please contact Groundlight support (axon-vision-support@axon.com).

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

This will install the Edge Endpoint doing GPU-based inference in the `edge` namespace in your k3s cluster and expose it via HTTPS on port 30143 on your local node. Helm will keep a history of the installation in the `default` namespace (signified by the `-n default` flag).

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

#### Variation: Enable HTTP

By default, the Edge Endpoint only serves HTTPS (with a self-signed certificate) on port 30143. Unencrypted HTTP on port 30101 is disabled by default. If you need HTTP access (for example, for local development or clients that can't handle the self-signed certificate), set `httpEnabled=true`:

```shell
helm upgrade -i -n default edge-endpoint edge-endpoint/groundlight-edge-endpoint \
  --set groundlightApiToken="${GROUNDLIGHT_API_TOKEN}" \
  --set httpEnabled=true
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

Now you can access the Edge Endpoint at `https://localhost:30143` (it uses a self-signed TLS certificate, so set `DISABLE_TLS_VERIFY=1` or pass `disable_tls_verification=True` to the `Groundlight()` constructor). For use with the Groundlight SDK, you can set the `GROUNDLIGHT_ENDPOINT` environment variable to `https://localhost:30143`.

### Uninstalling Edge Endpoint

To remove the Edge Endpoint deployed with Helm:

```bash
helm uninstall -n default edge-endpoint
```

## Troubleshooting Deployments

Here are some common issues you might encounter when deploying the edge endpoint and how to resolve them. If you have an issue that's not listed here, please contact Groundlight support at [axon-vision-support@axon.com](mailto:axon-vision-support@axon.com) for more assistence.

### Helm deployment fails with `validate-api-token` error

If you see an error like this when running the Helm install command:
```
Error: failed pre-install: 1 error occurred:
        * job validate-api-token-edge failed: BackoffLimitExceeded
```
it means that the API token you provided is not giving access.

There are two possible reasons for this:
1. The API token is invalid. Check the value you're providing and make sure it maps to a valid API token in the Groundlight web app.
2. Your account does not have permission to use edge services. Not all plans enable edge inference. To find out more and get your account enabled, contact Groundlight support at [axon-vision-support@axon.com](mailto:axon-vision-support@axon.com).

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

Image pulls use short-lived ECR credentials refreshed by the `refresh-ecr-creds`
CronJob (created by the Helm chart). Check recent runs:

```shell
kubectl get cronjob -n edge refresh-ecr-creds
kubectl logs -n edge -l app=refresh-ecr-creds --tail=100
```

If the job is failing, the Groundlight API token is often invalid or not authorized
to fetch reader credentials, or the upstream endpoint is unreachable. Confirm the
`groundlight-api-token` secret and that pods can reach `upstreamEndpoint`.

### Changing IP Address Causes DNS Failures and Other Problems

When the host IP changes, k3s DNS (CoreDNS) can break until the cluster is restarted.
The Helm chart enables a network healer by default that detects this and restarts k3s;
see [Disable the network healer](#variation-disable-the-network-healer) if you need to
turn that off. On a laptop or other device that moves between networks, leave it enabled.

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
## Building custom images

### Local development (edge-endpoint)

Build into the local k3s cluster with the fixed `dev` tag (no ECR push):

```shell
./deploy/bin/build-local-edge-endpoint-image.sh
```

FIPS (`Dockerfile.fips`, linux/amd64). Same `dev` tag and Helm values. Docker must be able to pull `cgr.dev/axon.com` first (`deploy/bin/ensure-chainguard-auth.sh`):

- Laptop: `chainctl auth login --org-name axon.com` then `chainctl auth configure-docker`.
- Headless: on a machine with a browser, `chainctl auth pull-token create --parent 644ce05dcfa4a1ac9e410de97e5b0d7f3194c656 --ttl=2h -o json`. On the build host, remove any `credHelpers["cgr.dev"]` from `~/.docker/config.json`, then `docker login cgr.dev` with that `identity_id` / `token`. Do not set `CI=true` to skip auth.

```shell
./deploy/bin/build-local-edge-endpoint-image-fips.sh
```

That defaults to the Axon-dev image name (`216731772508.../edge/edge-endpoint:dev`). For GL_Public naming:

```shell
ECR_ACCOUNT=767397850842 EDGE_ENDPOINT_IMAGE=edge-endpoint \
  ./deploy/bin/build-local-edge-endpoint-image-fips.sh
```

```shell
helm upgrade -i -n default edge-endpoint ./deploy/helm/groundlight-edge-endpoint \
  --set groundlightApiToken="${GROUNDLIGHT_API_TOKEN}" \
  --set edgeEndpointTag=dev
```

Helm sets `imagePullPolicy=Never` for the `dev` tag so Kubernetes uses the local image.

### Push to ECR (edge-endpoint)

```shell
# Tag is based on the current git commit; the script prints it
./deploy/bin/build-push-edge-endpoint-image.sh
```

```shell
helm upgrade -i -n default edge-endpoint edge-endpoint/groundlight-edge-endpoint \
  --set groundlightApiToken="${GROUNDLIGHT_API_TOKEN}" \
  --set edgeEndpointTag="<your-image-tag>"
```

### Inference image

Built from zuuul (`predictors/serving/`). See that repo's serving README, then pass
`--set inferenceTag=<your-image-tag>` (or `inferenceTag=dev` for a local build).

### Image tag knobs

`imageTag` is the shared default for both images.
`edgeEndpointTag` and `inferenceTag` override that default for one image only.
