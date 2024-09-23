
# Setting up the Edge Endpoint

The edge endpoint is run as a k3s deployment. Follow the steps below to get it set up.

## Starting the k3s Cluster 

If you don't have [k3s](https://docs.k3s.io/) installed, go ahead and install it by running 

```shell
> ./deploy/bin/install-k3s.sh
```


If you intend to run motion detection, make sure to add the detector ID's to the 
[edge config file](../configs/edge-config.yaml). For edge inference, adding detector ID's to the config file will cause
inference pods to be initialized automatically for each detector. Even if they aren't configured in the config file, 
edge inference will be set up for each detector ID for which the Groundlight service receives requests (note that it 
takes some time for each inference pod to become available the first time).

Before starting the cluster, you need to create/specify the namespace for the deployment. If you're creating a new one, run:

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

# Choose an inference flavor, either CPU or (default) GPU (note that appropriate setup for GPU must be done separately)
export INFERENCE_FLAVOR="CPU" / export inference_flavor = "GPU"
```

You'll also need to configure your AWS credentials using `aws configure` to include credentials that have permissions to pull from the appropriate ECR location (if you don't already have the AWS CLI installed, refer to the instructions [here](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)).

To start the cluster, run 
```shell 
> ./deploy/bin/cluster_setup.sh
```

Sometimes it might be desirable to reset all database tables(i.e., delete all existing data) for a fresh start. In that case, 
you will need to start the cluster with an extra argument:

```shell
> ./deploy/bin/cluster_setup.sh db_reset
```

This will create the edge-endpoint deployment with two containers: one for the edge logic and another one for creating/updating inference
deployments. After a while you should be able to see something like this if you run `kubectl get pods`:

```shell
NAME                                    READY   STATUS    RESTARTS   AGE
edge-endpoint-594d645588-5mf28          2/2     Running   0          4s
```

If you added detectors to the [edge config file](../configs/edge-config.yaml), you should also see a pod for each of them, e.g.:

```shell
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
then using that ID in the [edge_deployment](/edge-endpoint/deploy/k3s/edge_deployment.yaml) file. 

Follow the following steps:

```shell
# Build and push image to ECR
> ./deploy/bin/build-push-edge-endpoint-image.sh 
```


