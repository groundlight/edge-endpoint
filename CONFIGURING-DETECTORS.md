# Configuring Detectors for Edge Inference

## Do I need to configure my detectors?

Detector-specific configuration is NOT necessary for basic use of the edge endpoint. Once the edge endpoint is running, submitting an image query to it will create an edge inference pod for the specified detector. This inference pod will be created with the default settings. Note that it will take some time for the inference pod to start, especially the first time the edge endpoint is set up, and requests sent to the corresponding detector during that time will be redirected to the cloud. Once the inference pod has loaded the edge model and is ready to serve requests, it will begin attempting to answer image queries sent to that detector. If the answer from the edge model has confidence above the confidence threshold for the detector, you'll receive the answer from the edge model. If the confidence isn't high enough, it will escalate the query to the cloud. 

## Why would I want to configure detectors?

Configuring detectors for the edge endpoint allows you to provide fine-grained control over their behavior on the edge. By configuring a detector, you can:
* Automatically create an inference pod for the detector every time the edge endpoint starts up, ensuring it's ready to serve requests without having to first submit a query to it
* Configure the detector to always return the edge model's answer, regardless of the confidence
* Configure the detector to never escalate queries to the cloud
* Specify a maximum frequency for cloud escalations from the detector

## How do I configure a detector?

Detector configurations are specified in [edge-config.yaml](configs/edge-config.yaml). The file has three sections: `global_config`, `edge_inference_configs`, and `detectors`. 

NOTE: After modifying the config file, you'll have to re-run [setup-ee.sh](deploy/bin/setup-ee.sh) for your changes to be reflected.

### `global_config`

The global config contains parameters that affect the overall behavior of the edge endpoint. 

#### `refresh_rate`

`refresh_rate` is a float that defines how often the edge endpoint will attempt to fetch updated ML models (in seconds). If you expect a detector to frequently have a better model available, you can reduce this to ensure that the improved models will quickly be fetched and deployed. For example, you may want to label many image queries on a new detector. A higher refresh rate will ensure that the latest model improvements from these labels are promptly deployed to the edge. In practice, you likely won't want this to be lower than ~30 seconds due to the time it takes to train and fetch new models. If not specified, the default is 60 seconds.

### `edge_inference_configs`

Edge inference configs are 'templates' that define the behavior of a detector on the edge. Each detector you configure will be assigned one of these templates. There are some predefined configs that represent the main ways you might want to configure a detector. However, you can edit these and also create your own as you wish.

#### Structure of an edge_inference_config

For each edge inference config, you can configure various parameters. For a complete description of each, see [Reference: Edge Inference Parameters](#reference-edge-inference-parameters) below.

#### Predefined edge inference configs

There are a few predefined configs in the configuration file. These make use of the available edge inference parameters to achieve different kinds of behavior. If you're just getting started with setting up the edge endpoint, we recommend choosing from these based on which best fits your desired behavior!

##### `default`
```
default: # Return the edge model's prediction if sufficiently confident; otherwise, escalate to the cloud.
    enabled: true
    always_return_edge_prediction: false
    disable_cloud_escalation: false
```
This is the default behavior for a detector on the edge and is likely what you'll want to use most of the time, unless you have a specific reason to use a different configuration.

##### `edge_answers_with_escalation`
```
edge_answers_with_escalation: # Always return the edge model's predictions, but still escalate to cloud if unconfident.
    enabled: true
    always_return_edge_prediction: true
    disable_cloud_escalation: false
    min_time_between_escalations: 2.0
```
Use this config if: you want all answers to come from the edge model to ensure quick response times. This will happen regardless of the answers' confidence. However, your unconfident queries will be escalated to the cloud. This allows Groundlight (or you!) to provide labels on your detector so your model can improve over time.

##### `no_cloud`
```
no_cloud: # Always return the edge model's prediction and never escalate to the cloud.
    enabled: true
    always_return_edge_prediction: true
    disable_cloud_escalation: true
```
Use this config if: you always want the fastest answers from the edge model and don't want any image queries to get escalated to the cloud. This might be useful under circumstances such as limited network bandwith. Be careful using this option: if unconfident queries aren't escalated to the cloud, the model won't be able to receive new labels and improve. 

##### `disabled`
```
disabled:
    enabled: false
```
Use this config if: you don't want the edge endpoint to accept image queries for this detector.

### `detectors`

This section is where you define your detectors, along with the edge inference config to use for each of them. The structure looks like:
```
detectors:
    - detector_id: "det_abc"
        edge_inference_config: "default"
    - detector_id: "det_xyz"
        edge_inference_config: "my_custom_config"
```
Add a new entry for each detector that you want to configure. Each entry must include the detector ID and the edge inference config you want the detector to use. You can select one of the predefined edge inference configs or define a new one to achieve your desired behavior. 

Edge inference configs can be applied to as many detectors as you'd like, so if you want multiple detectors to have the same configuration, just assign them the same inference config. Make sure you don't have multiple entries for the same detector - in this case, the edge endpoint will error when starting up.

## Reference: Edge Inference Parameters

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