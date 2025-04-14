# Installing on an NVIDIA Jetson.

1) Install ubuntu, following NVIDIA's instructions.  Then update the OS.

```
sudo apt-get update
sudo apt-get dist-upgrade
```

2) Clone this repo onto the machine.

```
git clone https://github.com/groundlight/edge-endpoint
```

3) Install k3s

```
./deploy/bin/install-k3s.sh cpu
```

or run `~/edge-endpoint/deploy/bin/install-k3s.sh cpu`

4) AWS credentials

Make sure you are logged in with a valid AWS account to get the container images.

```
aws sts get-caller-identity
```


5) Setup the edge endpoint.

```
./deploy/bin/setup-ee.sh
```

6) Figure out the URL of the edge endpoint.

```
kubectl get service edge-endpoint-service
```

This IP address and port are your URL for `GROUNDLIGHT_ENDPOINT`