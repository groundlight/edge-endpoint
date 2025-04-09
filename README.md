# Edge Endpoint Helm Repository

We use Github Pages to host our Helm Repository. This repository only contains the Helm chart for the Edge-endpoint project - named `groundlight-edge-endpoint`.

The repo is automatically updated by the CI/CD pipeline whenever the main branch is deployed as "release". 

## Usage

To install the edge-endpoint chart, add the repository to your Helm configuration:

```bash
helm repo add edge-endpoint https://code.groundlight.ai/edge-endpoint/
helm repo update
```

Make sure that you've set the `GROUNDLIGHT_API_TOKEN` environment variable
    to your Groundlight API token.

Then you can install the chart:

```bash
helm upgrade -i -n default edge-endpoint edge-endpoint/groundlight-edge-endpoint \
    --set groundlightApiToken=${GROUNDLIGHT_API_TOKEN}
```
