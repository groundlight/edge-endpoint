
## Starting the k3s Cluster 

If you don't have [k3s](https://docs.k3s.io/) installed, go ahead and install it by running 

```shell
> ./deploy/install_k3s.sh
```

Before we can start the edge-endpoint kubernetes deployment, we need to first ensure that 
the `GROUNDLIGHT_API_TOKEN` is set. Once you have the token, then go ahead and run the following
script to create a kubernetes secret for it. 

```shell
> ./deploy/make-gl-api-token-secret.sh
```

For now we have a hard-coded docker image from ECR in the [edge-endpoint](/edge-endpoint/deploy/k3s/edge_deployment.yaml) 
deployment. If you want to make modifications to the code inside the endpoint and push a different 
image to ECR see [Pushing/Pulling Images from ECR](#pushingpulling-images-from-elastic-container-registry-ecr).

To start the kubernetes deployment, run 
```shell
> kubectl apply -f deploy/k3s/edge_deployment.yaml
```

This will create two k3s resources: our edge-endpoint service of type NodePort and our edge-endpoint
deployment. For simplicity, the service, deployment and pod names (even container names) are all 
edge-endpoint. Hopefully this will not be a source of confusion. 

After a while you should be able to see something like this if you run `kubectl get pods`:

```shell
NAME                             READY   STATUS    RESTARTS   AGE
edge-endpoint-594d645588-5mf28   1/1     Running   0          4s
```


## Pushing/Pulling Images from Elastic Container Registry (ECR)

We currently have a hard-coded docker image in our k3s deployment, which is not ideal. 
If you're testing things locally and want to use a different docker image, you can do so
by first creating a docker image locally, pushing it to ECR, retrieving the image ID and 
then using that ID in the [edge_deployment](/edge-endpoint/deploy/k3s/edge_deployment.yaml) file. 

Follow the following steps:

```shell
# Creating our edge-endpoint docker image. Make sure you are in the root directory
> docker build --target production-image --tag edge-endpoint .

# Check that the image was created successfully
> docker images 

# Push the image to ECR 
> ./deploy/push-edge-endpoint-image.sh

```

Once you've pushed the image to the remote registry, you can retrieve the image ID and add temporarily
use it in the deployment file. To apply the changes to the deployment, run 

```shell
kubectl scale deployment edge-endpoint --replicas=1 --namespace=default
```

