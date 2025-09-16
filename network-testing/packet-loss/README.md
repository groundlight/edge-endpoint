# Using Chaos Mesh to enable configurable packet loss

Chaos Mesh offers various types of fault simulation and can easily be integrated into a kubernetes deployment.

## Installation for K3s using Helm

Assuming Helm is installed as detailed in the main edge endpoint deployment instructions, it's easy to add Chaos Mesh. 

Follow the instructions in the [Chaos Mesh documentation for installation using Helm](https://chaos-mesh.org/docs/production-installation-using-helm/).

## How we use this to test the edge endpoint

So far, Chaos Mesh has only been used to test the edge endpoint's behavior while experiencing packet loss. 

To do this, the edge endpoint should be deployed as normal. Once ready to introduce the fault, follow the applicable instructions under [Currently Supported Faults](#currently-supported-faults) below.



To do this, the edge endpoint should be deployed with no faults enabled. Image query requests should be sent to ensure that the edge endpoint workers have a cached `Groundlight` API client (to make this easier, you may want to set the number of workers for the edge logic server to 1 prior to deploying). 

Once 

## Currently supported faults

### Packet loss 

This fault simulates packet loss and can be configured in various ways. See [the Chaos Mesh documentation](https://chaos-mesh.org/docs/simulate-network-chaos-on-kubernetes/#loss) for full details. 

To apply the fault, run:
```bash
k apply -f packet-loss.yaml
```

This will create a `NetworkChaos` named `drop-traffic`. By default the fault is configured to affect only outbound traffic from the `edge-endpoint` pod to `api.groundlight.ai`, with 50% loss and a correlation value of 75.

To check that the fault has been applied currently, run:
```bash
k get networkchaos
```
You should see something like:
```
NAME           ACTION   DURATION
drop-traffic   loss
```

To remove the fault, simply run:
```bash
k delete networkchaos drop-traffic
```
