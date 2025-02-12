
# Setting up the Edge Endpoint

The edge endpoint runs under kubernetes, typically on a single-node cluster, which could be just a raspberry pi, or a powerful GPU server.  But if you have a lot of detectors to run locally, it will scale out to a large multi-node cluster as well with basically zero changes except to the k8 cluster setup. 

The instructions below are fairly opinionated, optimized for single-node cluster setup, using k3s, on an Ubuntu/Debian-based system.  If you want to set it up with a different flavor of kubernetes, that should work, but you'll have to figure out how to do that yourself.

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

(Note: these scripts depend on the Linux utilities `curl` and `jq`. If these aren't on your system, the scripts will install them for you.)

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

If you configured detectors in the [edge config file](/configs/edge-config.yaml), you should also see a pod for each of them, e.g.:

```
NAME                                                              READY   STATUS    RESTARTS   AGE
edge-endpoint-594d645588-5mf28                                    2/2     Running   0          4s
inferencemodel-det-3jemxiunjuekdjzbuxavuevw15k-5d8b454bcb-xqf8m   1/1     Running   0          2s
```

We currently have a hard-coded docker image from ECR in the [edge-endpoint](/edge-endpoint/deploy/k3s/edge_deployment.yaml)
deployment. If you want to make modifications to the edge endpoint code and push a different
image to ECR see [Pushing/Pulling Images from ECR](#pushingpulling-images-from-elastic-container-registry-ecr).


## Troubleshooting Deployments

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
