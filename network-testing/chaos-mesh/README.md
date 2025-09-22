# Using Chaos Mesh to simulate network faults

Chaos Mesh offers various types of fault simulation and can easily be integrated into a kubernetes deployment.

The faults we currently support are:
- Packet loss: drop packets with configurable probability. See [Packet loss](#packet-loss).

## Installation for K3s using Helm

Once Helm is installed as detailed in the main [edge endpoint deployment instructions](/deploy/README.md), it's easy to add Chaos Mesh. 

Follow the instructions in the [Chaos Mesh documentation for installation using Helm](https://chaos-mesh.org/docs/production-installation-using-helm/).

## How we use this to test the edge endpoint

So far, Chaos Mesh has only been used to test the edge endpoint's behavior while experiencing packet loss. 

To do this, the edge endpoint should be deployed as normal. Once you're ready to introduce the fault, follow the applicable instructions under [Currently Supported Faults](#currently-supported-faults) below.

Once the fault has been added, trigger the behavior you wish to test for the edge endpoint (e.g., escalating queries from the escalation queue) and observe the behavior.

## Currently supported faults

### Packet loss 

This fault simulates packet loss. See [the Chaos Mesh documentation](https://chaos-mesh.org/docs/simulate-network-chaos-on-kubernetes/#loss) for full details and configuration options.

To apply the fault, run:
```bash
k apply -f faults/packet-loss.yaml
```

This will create a `NetworkChaos` named `packet-loss`. By default the fault is configured to affect only outbound traffic from the `edge-endpoint` pod to `api.groundlight.ai`, with 50% loss and a correlation value of 75. To change these values, edit [packet-loss.yaml](faults/packet-loss.yaml) and re-apply the fault.

To check that the fault has been applied currently, run:
```bash
k get networkchaos
```
You should see something like:
```
NAME          ACTION   DURATION
packet-loss   loss
```

If you want to view the configuration, run:
```bash
k describe networkchaos packet-loss
```

To remove the fault, simply run:
```bash
k delete networkchaos packet-loss
```
