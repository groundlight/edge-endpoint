# Running the edge-endpoint via k3s on a balena device

## Setup
Tested using an EC2 m6 instance with 64GB disk. Everything except for the triton inference server works on a RaspberryPi 5 (which has a 64bit OS and 8Gb RAM), but the inference server is too demanding for the RPi5.

From the root of `edge-endpoint`, run:
```bash
balena login
balena push <your-fleet>
```
This will build and push two "services" to the edge devices in your chosen fleet. The first is a [k3s server](https://docs.k3s.io/architecture) named `server`, which effectively acts as our k3s cluster node. The second is the `bastion` service, from which a user can access the k3s cluster (e.g. by running `kubectl get nodes`). The `bastion` service also contains a copy of this repo at `/app/edge-endpoint`.

Now, we have our k3s cluster built and running, but we have not started our edge deployment.

Configure the following variables via the `<fleet>/Variables` or `<device>/Device Variables` interfaces on the BalenaCloud dashboard:
```
GROUNDLIGHT_API_TOKEN - so that we can authorize the fetching of edge model binaries
AWS_ACCESS_KEY_ID - so we can pull the edge-endpoint and gl-tritonserver images from ECR
AWS_SECRET_ACCESS_KEY - needed along with AWS_ACCESS_KEY_ID
```

Now, ssh into `bastion` and run the following:
```bash
cd /app/edge-endpoint
INFERENCE_FLAVOR="CPU" DEPLOYMENT_NAMESPACE="default" ./deploy/bin/cluster_setup.sh
```
