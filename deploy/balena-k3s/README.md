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

### Deploying to an x86 device with an NVIDIA GPU
Tested using an HP Victus Laptop with Intel Core i5 processor and NVIDIA GeForce RTX 3050 Laptop GPU.

From the root of `edge-endpoint`, run:
```bash
./deploy_balena.sh <my-fleet> gpu [balena_os_version]
```

The optional `balena_os_version` argument must match the balenaOS version running on the device
(defaults to `6.0.24%2Brev1`). This is needed to compile NVIDIA kernel modules against the correct
kernel headers.

### Deploying to a Jetson Orin device
From the root of `edge-endpoint`, run:
```bash
./deploy_balena.sh <my-fleet> jetson-orin
```

### What gets deployed

All flavors deploy two services:
1. A `server` service running a [k3s server](https://docs.k3s.io/architecture) as the cluster node
2. A `bastion` service that installs the edge-endpoint via Helm and provides kubectl/helm access

For GPU builds, NVIDIA kernel modules are compiled as part of the server image (multi-stage Docker
build) and loaded at runtime before k3s starts. No separate GPU container is needed.

### Configuration
Configure the following variables via the `<fleet>/Variables` or `<device>/Device Variables` interfaces on the BalenaCloud dashboard:
```
GROUNDLIGHT_API_TOKEN - Required. The Groundlight API token for authorization.
RUN_EDGE_ENDPOINT    - Set to "1" to deploy the edge-endpoint pods via Helm.
EDGE_CONFIG          - Optional. YAML contents for edge-config.
GROUNDLIGHT_ENDPOINT - Optional. Override the upstream Groundlight API endpoint.
EDGE_ENDPOINT_VALUES - Optional. Comma-separated key=value pairs passed as helm --set flags.
```

The bastion automatically detects the inference flavor (cpu/gpu/jetson) from the server container
and configures the Helm deployment accordingly. AWS credentials are handled by the Helm chart's
ECR credential jobs, so `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` no longer need to be set
as fleet variables.
