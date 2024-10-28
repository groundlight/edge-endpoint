
# Setting up the Edge Endpoint

The edge endpoint runs under kubernetes, typically on a single-node cluster, which could be just a raspberry pi, or a powerful GPU server.  But if you have a lot of detectors to run locally, it will scale out to a large multi-node cluster as well with basically zero changes except to the k8 cluster setup. 

The instructions below are fairly opinionated, optimized for single-node cluster setup, using k3s, on an Ubuntu/Debian-based system.  If you want to set it up with a different flavor of kubernetes, that should work, but you'll have to figure out how to do that yourself.

## Setting up Single-Node Kubernetes with k3s

If you don't have [k3s](https://docs.k3s.io/) installed, there are two scripts which can install it depending on whether you have a CUDA GPU or not.  If you don't set up a GPU, the models will run more slowly on CPU.

```shell
./deploy/bin/install-k3s.sh
# or to install on a GPU system
./deploy/bin/install-k3s-nvidia.sh
```

You might want to customize the [edge config file](../configs/edge-config.yaml) to include the detector ID's you want to run.  Adding detector ID's to the config file will cause inference pods to be initialized automatically for each detector. Even if they aren't configured in the config file,
edge inference will be set up for each detector ID for which the Groundlight service receives requests (note that it
takes some time for each inference pod to become available for the first time).

Before installing the edge-endpoint, you must pick a namespace for your edge-endpoint.  We recommend creating a new namespace.  In these examples we'll use `groundlight-edge` but you can use any name you like.

```
kubectl create namespace groundlight-edge
```

Whether you created a new namespace or are using an existing one, set the DEPLOYMENT_NAMESPACE environment variable:
```
export DEPLOYMENT_NAMESPACE="groundlight-edge"
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

You'll also need to configure AWS credentials which are authorized to pull from Groundlight's ECR repositories for the inference pods.
If your system is not already configured for this, contact Groundlight support to get the IAM credentials you need.
Once you have the credentials, you can configure them using `aws configure` to include credentials that have permissions to pull from the appropriate ECR location (if you don't already have the AWS CLI installed, refer to the instructions [here](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)).

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
