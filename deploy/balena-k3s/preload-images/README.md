## Pre-load required docker images for k3s startup

If you're working with a Balena device that can't access DockerHub (docker.io), you'll need 
to pre-load some images onto the device so that k3s can start correctly.

Pre-requisites: `docker` and the Balena CLI, `balena`.

Here are the steps:
1. cd into this directory
2. Run `balena login` if you're not logged into the Balena CLI
3. Run `./upload-k3s-required-images.sh <device-id>`
4. Go to the balena dashboard and restart the server and bastion containers
5. Open a shell on the bastion and run `k get pods` to check if edge-endpoint is running.