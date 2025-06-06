# Edge Endpoint Canaries

This directory contains canary scripts for various edge devices. 

We will start with an Ubuntu laptop, and will later add other devices such as a G4, a Balena Jetson, a non-Balena Jetson etc.

Each subdirectory contains an installation script, `install_cron.sh` that configures the environment and deploys any relevant cron jobs.

## Laptop

To deploy on a laptop follow these steps:
1. Flash Ubuntu onto the laptop. Ubuntu 22.04 is the recommended version. 24.04 does not work because it does not support the Nvidia container runtime.
1. Install the Edge Endpoint on the laptop following the typical [deployment instructions](/deploy/README.md). Configure your detector with a edge_inference_config of `edge_answers_with_escalation`. Specific instructions for doing this can be found in [CONFIGURING-DETECTORS.md](/CONFIGURING-DETECTORS.md)
1. Install the cronjobs: `./laptop/install_cron.sh`. This script will set everything up and tell you where to find the logs. 

### Tips for getting the laptop to not suspend when lid closes
You'll want to be able to close the lid on the laptop without it going to sleep, but Ubuntu 22.04 doesn't seem to have a built-in option for that. 

These steps have been successfully used to prevent the laptop from going to sleep when the lid shuts.
1. Get Gnome Tweaks: `sudo apt update && sudo apt install gnome-tweaks -y`
1. Press Super (Windows key) and search for Tweaks.
1. Open Gnome Tweaks.
1. Look for the setting "Suspend when laptop lid is closed".
1. Disable it.

## Jetson (Coming Soon)

## G4 (Coming Soon)