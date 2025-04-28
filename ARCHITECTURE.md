# Edge endpoint architecture

## Overview

The edge endpoint provides a way for clients to use the existing Groundlight API in a hybrid mode: most inference requests will be handled locally while all other requests will be forwarded to the Groundlight cloud service.

## Structure

The edge endpoint is implemented as a set of Kubernetes resources (defined by the helm chart in the [helm directory](deploy/helm/groundlight-edge-endpoint/)).

There is a single pod for the main logic of the edge endpoint and one pod for each inference model.

The edge endpoint pod divides its work between three containers:

| Container               | Function                                                                                                                                                           |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Edge Endpoint           | Handle inference requests and determine whether to handle them locally or send them to the cloud.                                                                  |
| Inference Model Updater | Keep track of which models are in use, download the latest model data, and start pods to serve inference on those models, updating to the latest models regularly. |
| Status Monitor          | Aggregate usage stats and upload them to the cloud periodically.                                                                                                   |

## Network flow

By default, the edge endpoint exposes the Groundlight API on port 30101 on the local machine.

<img src="images/Client request processing.excalidraw.png" alt="Client request processing" width="800"/>

How URLs are handled:

| URL                               | Verb(s) | Handled by                           |
| --------------------------------- | ------- | ------------------------------------ |
| `/image-queries`                  | `POST`  | Edge endpoint, may escalate to cloud |
| `/health/live`<br>`/health/ready` | `GET`   | Edge endpoint                        |
| `/ping`                           | `GET`   | Edge endpoint                        |
| `/status`                         | `GET`   | Status monitor                       |
| all others                        | all     | Forward to cloud                     |

The nginx server will always try to send API calls to the the edge endpoint first. If the edge endpoint cannot handle the request, it will forward it to the cloud service using the nginx fallback mechanism. The following sequence diagrams illustrate the process of handling requests:

Local inference 
```mermaid
sequenceDiagram
actor client
box Edge endpoint pod
participant nginx
participant edge-endpoint
end
participant inference pod
participant cloud service
client->>nginx: POST /image-queries
nginx->>edge-endpoint: POST /image-queries
edge-endpoint->>+inference pod: POST /infer
inference pod-->>-edge-endpoint: High-confidence result
edge-endpoint-->>nginx: result
nginx-->>client: result
```

Local inference with escalation 
```mermaid
sequenceDiagram
actor client
box Edge endpoint pod
participant nginx
participant edge-endpoint
end
participant inference pod
participant cloud service
client->>nginx: POST /image-queries
nginx->>edge-endpoint: POST /image-queries
edge-endpoint->>+inference pod: POST /infer
inference pod-->>-edge-endpoint: Low-confidence result
edge-endpoint->>+cloud service: POST /image-queries
cloud service-->>-edge-endpoint: result
edge-endpoint-->>nginx: result
nginx-->>client: result
```

Forward unsupported URL to cloud 
```mermaid
sequenceDiagram
actor client
box Edge endpoint pod
participant nginx
participant edge-endpoint
end
participant cloud service
client->>nginx: GET /me
nginx->>edge-endpoint: GET /me
edge-endpoint-->>nginx: ERROR 404
nginx->>+cloud service: GET /me
cloud service-->>-nginx: result
nginx-->>client: result
```

## Inference requests

<img src="images/edge-endpoint-inference-flow.excalidraw.png" alt="Inference flow" width="800"/>


## Communication between the edge endpoint containers

<img src="images/Edge container communication.excalidraw.png" alt="Communication between containers" width="800"/>


