
# Setting up the Edge Endpoint

The edge endpoint runs under kubernetes, typically on a single-node cluster, which could be just a raspberry pi, or a powerful GPU server.  But if you have a lot of detectors to run locally, it will scale out to a large multi-node cluster as well with basically zero changes except to the k8 cluster setup. 

The instructions below are fairly opinionated, optimized for single-node cluster setup, using k3s, on an Ubuntu/Debian-based system.  If you want to set it up with a different flavor of kubernetes, that should work, but you'll have to figure out how to do that yourself.

## Dependencies
Edge Endpoint requires `curl` and `jq` which are likely already on your system, but if you have a minimal Linux distribution, they might not be. To make sure you have them, run:

```shell
sudo apt update && sudo apt install -y jq curl
```

## Setting up Single-Node Kubernetes with k3s

If you don't have [k3s](https://docs.k3s.io/) installed, there are two scripts which can install it depending on whether you have a CUDA GPU or not.  If you don't set up a GPU, the models will run more slowly on CPU.

```shell
# For CPU inference
./deploy/bin/install-k3s.sh
```

```shell
# For GPU inference
./deploy/bin/install-k3s-nvidia.sh
```

You might want to customize the [edge config file](../configs/edge-config.yaml) to include the detector ID's you want to run.  Adding detector ID's to the config file will cause inference pods to be initialized automatically for each detector. Even if they aren't configured in the config file,
edge inference will be set up for each detector ID for which the Groundlight service receives requests (note that it
takes some time for each inference pod to become available for the first time).

Before installing the edge-endpoint, you need to create/specify the namespace for the deployment. If you're creating a new one, run:

```
kubectl create namespace "your-namespace-name"
```

Whether you created a new namespace or are using an existing one, set the DEPLOYMENT_NAMESPACE environment variable:
```
export DEPLOYMENT_NAMESPACE="your-namespace-name"
```

Some other environment variables should also be set. You'll need to have created
a Groundlight API token in the [Groundlight web app](https://app.groundlight.ai/reef/my-account/api-tokens).
```
# Set your API token
export GROUNDLIGHT_API_TOKEN="api_xxxxxx"

# Choose an inference flavor, either CPU or (default) GPU.
# Note that appropriate setup for GPU may need to be done separately.
export INFERENCE_FLAVOR="CPU"
# export INFERENCE_FLAVOR="GPU"
```

You'll also need to configure your AWS credentials using `aws configure` to include credentials that have permissions to pull from the appropriate ECR location (if you don't already have the AWS CLI installed, refer to the instructions [here](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)).

To install the edge-endpoint, run:
```shell
./deploy/bin/setup-ee.sh
```

This will create the edge-endpoint deployment which is the both the SDK proxy and coordination service. After a while you should be able to see something like this if you run `kubectl get pods`:

```
NAME                                    READY   STATUS    RESTARTS   AGE
edge-endpoint-594d645588-5mf28          2/2     Running   0          4s
```

If you added detectors to the [edge config file](../configs/edge-config.yaml), you should also see a pod for each of them, e.g.:

```
NAME                                                              READY   STATUS    RESTARTS   AGE
edge-endpoint-594d645588-5mf28                                    2/2     Running   0          4s
inferencemodel-det-3jemxiunjuekdjzbuxavuevw15k-5d8b454bcb-xqf8m   1/1     Running   0          2s
```

We currently have a hard-coded docker image from ECR in the [edge-endpoint](/edge-endpoint/deploy/k3s/edge_deployment.yaml)
deployment. If you want to make modifications to the edge endpoint code and push a different
image to ECR see [Pushing/Pulling Images from ECR](#pushingpulling-images-from-elastic-container-registry-ecr).


## Troubleshooting Deployments
### DNS Issues Inside Containers
If your edge-endpoint pod comes online, but none of your inference pods come online, you may be experiencing DNS issues inside the containers.
```bash
username@hostname:~/edge-endpoint$ kubectl get pods -n <YOUR-NAMESPACE>
NAME                                                              READY   STATUS             RESTARTS        AGE
edge-endpoint-78cddd689d-vls5m                                    2/2     Running            0               11m
```
You can confirm this by exec'ing into the inference-model-updater container.
```bash
kubectl exec -it edge-endpoint-<YOUR-PODS-ID> -n <YOUR-NAMESPACE> -c inference-model-updater -- /bin/bash
```
Try running `apt-get update`. It may fail with the following error message, indicating DNS issues.
```text
Err:1 https://deb.debian.org/debian bullseye InRelease
  Certificate verification failed: The certificate is NOT trusted. The certificate issuer is unknown. The name in the certificate does not match the expected.  Could not handshake: Error in the certificate verification. [IP: 192.168.1.1 443]
...
```
Notice how debian.org is resolving to a local IP address here. If this is the case, you can fix the issue by configuring the network to use Google’s DNS servers, bypassing the local router’s DNS.
#### Step 1: Confirm Your Network Interface

First, confirm the name of your network interface (often wlo1 for Wi-Fi or eth0 for Ethernet) by running:

```bash
nmcli device status
```
#### Step 2: Update DNS Settings with nmcli

Use nmcli to set the DNS servers to Google’s DNS (8.8.8.8 and 8.8.4.4) and ignore the DNS settings provided by DHCP:

```bash
sudo nmcli connection modify <YOUR-CONNECTION-NAME> ipv4.dns "8.8.8.8,8.8.4.4"
sudo nmcli connection modify <YOUR-CONNECTION-NAME> ipv4.ignore-auto-dns yes
```

Replace <YOUR-CONNECTION-NAME> with the name of your active connection, such as your Wi-Fi network name.
#### Step 3: Restart the Interface

Restart the connection to apply the changes:

```bash
sudo nmcli connection down <YOUR-CONNECTION-NAME> && sudo nmcli connection up <YOUR-CONNECTION-NAME>
```
#### Step 4: Confirm the Update Worked

Verify that the DNS settings have been applied correctly by running:

```bash
nmcli connection show "<YOUR-CONNECTION-NAME>" | grep ipv4.dns
```

This should show the configured DNS servers, `8.8.8.8` and `8.8.4.4`.

#### Step 5: Uninstall and Reinstall k3s.
Uninstall by running `sudo /usr/local/bin/k3s-uninstall.sh`.

Reinstall by following the instructions earlier in this readme.

This should resolve the DNS issue and allow the inference pods to launch.

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
