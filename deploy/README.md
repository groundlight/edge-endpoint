
## Getting Started 

If you don't have [k3s]() installed, go ahead and install it by running 

```shell
> ./deploy/install_k3s.sh
```


## Modifying the Edge Configuration

We provide [edge.yaml](../configs/edge.yaml) file to set up custom configuration options that 
are currently supported by the edge endpoint. Currently, this is restricted to motion detection. 
For instance, you might want to add a new detector ID in order to start running motion detection 
on the corresponding detector. Once you've updated the configuration as needed, you need to update
the ConfigMap in kubernetes so that those changes take effect. Simply run

```shell
> kubectl create configmap edge-config-yaml \
    --from-file=configs/edge.yaml \
    --dry-run=client -o yaml \
    | kubectl apply -f - 
```


