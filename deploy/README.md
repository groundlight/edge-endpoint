
## Starting the k3s Cluster 

If you don't have [k3s](https://docs.k3s.io/) installed, go ahead and install it by running 

```shell
> ./deploy/bin/install_k3s.sh
```


If you intend to run motion detection, make sure to add the detector ID's to the [edge config file](/configs/edge-config.yaml). 
If you only intend to run edge inference, you don't need to configure any detectors. By default, edge inference will be set up for 
each detector ID for which the Groundlight service receives requests. 

To start the cluster, run 
```shell 
> ./deploy/bin/cluster_setup.sh
```

This will create the edge-endpoint deployment with two containers: one for the edge logic and another one for creating/updating inference
deployments. After a while you should be able to see something like this if you run `kubectl get pods`:

```shell
NAME                             READY   STATUS    RESTARTS   AGE
edge-endpoint-594d645588-5mf28   2/2     Running   0          4s
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


