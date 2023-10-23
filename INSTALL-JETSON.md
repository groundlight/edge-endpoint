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
./deploy/bin/install-k3s.sh
```

or run `~/edge-endpoint/deploy/bin/install-k3s.sh`

4) AWS credentials

Make sure you are logged in with a valid AWS account to get the container images.

```
aws sts get-caller-identity
```


5) Setup the cluster.

```
./deploy/bin/cluster_setup.sh
```
