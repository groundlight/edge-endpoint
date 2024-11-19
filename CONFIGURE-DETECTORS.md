# Configuring detectors for edge inference

## Do I need to configure my detectors?

No detector-specific configuration is necessary for basic use of the edge endpoint. Once it's running, submitting an image query to the edge endpoint will automatically trigger the creation of an edge inference pod for the specified detector. This inference pod will be created with the default settings. Once the pod has loaded the model and is ready to serve requests, the edge model will begin attempting to answer image queries sent to it. If its confidence is above the confidence threshold for the detector, you'll receive the answer from the edge model. If the confidence is too low, it will escalate the query to the cloud. 

## Why would I want to configure detectors for the edge?

Configuring detectors for the edge endpoint allows you to provide finer-grained control over their behavior on the edge. By configuring a detector, you can:
* Have the edge endpoint automatically create an inference pod for a detector, making it ready to serve requests without having to first submit a query to it
* Configure a detector to always return the edge model's answer, regardless of the confidence
* Make a detector never escalate queries to the cloud
* Specify a maximum frequency for cloud escalations

## How do I configure a detector?

Detector configurations are specified in [edge-config.yaml](configs/edge-config.yaml). There are three sections: `global_config`, `edge_inference_configs`, and `detectors`.

### `global_config`

The global config contains parameters that affect the overall behavior of the edge endpoint. 

#### `refresh_rate`

The `refresh_rate` parameter is a float that defines how often the edge endpoint will attempt to fetch updated ML models (in seconds). If you expect a detector to frequently have a better model available, such as if you are labeling many image queries for a new detector, you can set this to be lower to ensure that the improved models will be fetched quickly. In practice, you likely won't want this to be lower than ~30 seconds due to the time it takes to train new models. If not specified, the default is 60 seconds.

### `edge_inference_configs`

Edge inference configs are 'templates' that define the behavior of a detector on the edge. Each detector you configure will be assigned one of these templates. There are some pre-defined configs that represent the main ways you might want to configure a detector. However, you can edit these and also create your own as you wish.

#### Structure of an `edge_inference_config`

For each edge inference config, you can configure various parameters. For a complete description of each, see [Appendix: edge inference parameters](#appendix-edge-inference-parameters) below.

#### Pre-defined edge inference configs

There are a few pre-defined configs that represent the main ways you might want to configure a detector. 

##### `default`
```
default: # Return the edge model's prediction if sufficiently confident; otherwise, escalate to the cloud.
    enabled: true
    always_return_edge_prediction: false
    disable_cloud_escalation: false
```
This is the default behavior for a detector on the edge and is likely what you'll want to use most of the time, unless you have a specific reason to use a different configuration.

##### `edge-answers-with-escalation`
```
edge-answers-with-escalation: # Always return the edge model's predictions, but still escalate to cloud if unconfident.
    enabled: true
    always_return_edge_prediction: true
    disable_cloud_escalation: false
    min_time_between_escalations: 2.0
```
Use this config if: you want the fastest answers from the edge model (regardless of confidence), but also want unconfident queries to be escalated to the cloud at a reasonable rate so that you can provide labels and continue improving the models.

##### `no-cloud`
```
no-cloud: # Always return the edge model's prediction and never escalate to the cloud.
    enabled: true
    always_return_edge_prediction: true
    disable_cloud_escalation: true
```
Use this config if: you always want the fastest answers from the edge model and don't want any image queries to get escalated to the cloud.

##### `disabled`
```
disabled:
    enabled: false
```
Use this config if: you don't want the edge endpoint to accept image queries for this detector.

### `detectors`

This section is where you define detectors to be configured, along with the edge inference config to use for each of them. The structure looks like:
```
- detector_id: "det_abc"
    edge_inference_config: "default"
- detector_id: "det_xyz"
    edge_inference_config: "no-cloud"
```
You'll add a new entry for each detector that you want to configure. Remember that inference configs can be applied to as many detectors as you'd like, so if you want multiple detectors to have the same configuration, just associate them with the same edge inference config. Make sure you don't have multiple entries for the same detector - in this case, the edge endpoint will error when starting up.

## Appendix: edge inference parameters

### `enabled` - default `true`
Whether the edge endpoint should accept image queries for the associated detector. Generally you'll want this to be `true` for detectors that you're configuring.

### `api_token` - default `null`
The API token to use for fetching the inference model for the associated detector. Most of the time this should be left blank, which will default to using the Groundlight API token set as an environment variable. If you are configuring detectors owned by multiple accounts, you could specify different API tokens to be used for each detector.  

### `always_return_edge_prediction` - default `false`
Whether the edge model's answer should always be returned, regardless of the answer's confidence. When this is `false` (the default behavior), the edge model's answer will only be returned if it is above the confidence threshold. If the confidence is not sufficiently high, the query will be escalated to the cloud, which may result in a longer wait for the answer. If you always want to receive fast answers from a detector and don't want to enforce that answers will be above the confidence threshold, you should set this to `true`. 

### `disable_cloud_escalation` - default `false`
Whether escalations to the cloud should be disabled. This can only be set to `true` if `always_return_edge_prediction` is also `true`. When `always_return_edge_prediction` is `true` and `disable_cloud_escalation` is `false`, fast answers from the edge model will be returned regardless of their confidence but insufficiently confident answers will still be escalated to the cloud in the background, allowing you to provide more labels and continue improving the model. You should set this to `true` if you don't need the model to improve and have a reason to not want any image queries to be escalated to the cloud.

### `min_time_between_escalations` - default `2.0`
The minimum number of seconds to wait between escalating image queries to the cloud. This ensures that a large amount of unconfident (and likely visually-similar) queries are not escalated within a short timespan, such as when beginning to submit queries to a new detector. This can be configured to ensure a specific query rate-limit is not exceeded. Unless you have a reason to do so, reducing this below `2.0` is not recommended. 