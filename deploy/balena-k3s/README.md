# Running the edge-endpoint via k3s on a balena device

## Setup
First, install the balena CLI. You can find installation instructions for your platform at https://github.com/balena-io/balena-cli/blob/master/INSTALL.md

Once installed, log in to your balena account:
```bash
balena login
```

## Deploying the edge-endpoint to a balena-managed device

### Deploying to a CPU-only device
Tested using an EC2 m6 instance with 64GB disk. Also known to work on a Raspberry Pi 5 with 8GB of RAM.

From the root of `edge-endpoint`, run:
```bash
./deploy_balena.sh <my-fleet> cpu
```

This will build and push two services to the edge devices in your chosen fleet:
1. A `server` service running a [k3s server](https://docs.k3s.io/architecture) that acts as the k3s cluster node
2. A `bastion` service that provides access to the k3s cluster via kubectl commands and contains a copy of this repo at `/app/edge-endpoint`

Now, we have our k3s single-node cluster built and running, but we have not started our edge deployment. To do this,
see the [Configuration](#Configuration) section below (specifically, you will need to set the `RUN_EDGE_ENDPOINT` variable).

### Deploying to an x86 device with an NVIDIA GPU
Tested using an HP Victus Laptop with Intel Core i5 processor and NVIDIA GeForce RTX 3050 Laptop GPU.

From the root of `edge-endpoint`, run:
```bash
./deploy_balena.sh <my-fleet> gpu
```

This will build and push three services to the edge devices in your chosen fleet:
1. A `gpu` service that loads the compiled NVIDIA driver kernel module into the host OS, enabling GPU access for other services
2. A `server` service running a [k3s server](https://docs.k3s.io/architecture) that acts as the k3s cluster node and installs the NVIDIA GPU operator for Kubernetes GPU support
3. A `bastion` service that provides access to the k3s cluster via kubectl commands and contains a copy of this repo at `/app/edge-endpoint`

Now, we have our k3s single-node cluster built and running, but we have not started our edge deployment. To do this,
see the [Configuration](#Configuration) section below (specifically, you will need to set the `RUN_EDGE_ENDPOINT` variable).

### Deploying to a Jetson Orin device
Not yet tested

From the root of `edge-endpoint`, run:
```bash
./deploy_balena.sh <my-fleet> jetson-orin
```

This will build and push three services to the edge devices in your chosen fleet:
1. A `server-jetson` service running a [k3s server](https://docs.k3s.io/architecture) that acts as the k3s cluster node and installs the NVIDIA GPU operator for Kubernetes GPU support
2. A `bastion` service that provides access to the k3s cluster via kubectl commands and contains a copy of this repo at `/app/edge-endpoint`

Now, we have our k3s single-node cluster built and running, but we have not started our edge deployment. To do this,
see the [Configuration](#Configuration) section below (specifically, you will need to set the `RUN_EDGE_ENDPOINT` variable).

### Configuration
Configure the following variables via the `<fleet>/Variables` or `<device>/Device Variables` interfaces on the BalenaCloud dashboard:
```
GROUNDLIGHT_API_TOKEN - so that we can authorize the fetching of edge model binaries
AWS_ACCESS_KEY_ID - so we can pull the edge-endpoint and gl-edge-inference images from ECR
AWS_SECRET_ACCESS_KEY - needed along with AWS_ACCESS_KEY_ID
RUN_EDGE_ENDPOINT - Set this to anything (such as "1") to start the pods (added for glhub integration)
```

## Extras:
Dockerfile will automatically run the following command as `bastion` launches so no need to run this anymore but leaving this command as a reference if we need to start the clusters manually.

```bash
cd /app/edge-endpoint
INFERENCE_FLAVOR="CPU" DEPLOYMENT_NAMESPACE="default" ./deploy/bin/setup-ee.sh
```
