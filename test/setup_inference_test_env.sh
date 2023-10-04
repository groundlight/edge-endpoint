#!/bin/bash 

EDGE_CONFIG=$(cat <<- EOM
motion_detection_templates:
  default:
    enabled: true
    val_threshold: 50
    percentage_threshold: 5.0
    max_time_between_images: 45

  super-sensitive:
    enabled: true
    val_threshold: 5
    percentage_threshold: 0.05
    max_time_between_images: 45

  disabled:
    enabled: false

local_inference_templates:
  default:
    enabled: true 
    refresh_rate: 120
  disabled:
    enabled: false

detectors:
  - detector_id: 'det_2UOxalD1gegjk4TnyLbtGggiJ8p'
    motion_detection_template: 'disabled'
    local_inference_template: 'default'

  - detector_id: 'det_2UOxao4HZyB9gv4ZVtwMOvdqgh9'
    motion_detection_template: 'disabled'
    local_inference_template: 'default'
EOM
)

export EDGE_CONFIG