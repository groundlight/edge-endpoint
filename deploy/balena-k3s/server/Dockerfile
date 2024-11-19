# References:
# https://k3d.io/v5.7.4/usage/advanced/cuda/#building-a-customized-k3s-image
# https://github.com/k3s-io/k3s/blob/master/package/Dockerfile

ARG K3S_TAG="v1.28.8+k3s1"

# Use this instead of, for example, balenalib/genericx86-64-ext-ubuntu:focal, because
# it is cross-platform and can be used on any architecture / type of device.
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND noninteractive

# Install Nvidia driver. Must match version in gpu container exactly
RUN \
    apt-get update && \
    apt install -y curl runc software-properties-common && \
    add-apt-repository ppa:graphics-drivers/ppa && \
    apt update && \
    apt install -y nvidia-driver-550 \
    && rm -rf /var/lib/apt/lists/*

# Install K3s binary (also installs containerd)
RUN curl -sfL https://get.k3s.io | INSTALL_K3S_SKIP_START=true INSTALL_K3S_SKIP_ENABLE=true INSTALL_K3S_VERSION=${K3S_TAG} sh

# Install the NVIDIA container toolkit
RUN curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg \
    && curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
      sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
      tee /etc/apt/sources.list.d/nvidia-container-toolkit.list \
    && apt-get update && apt-get install -y nvidia-container-toolkit \
    && rm -rf /var/lib/apt/lists/* \
    && nvidia-ctk runtime configure --runtime=containerd

# Add nvidia-gpu-operator manifest
RUN mkdir -p /opt/k3s/manifests/
COPY manifests/nvidia-gpu-operator.yaml /opt/k3s/manifests/

# Make pinamod-public directory for hostmapped volume
RUN mkdir -p /opt/groundlight/edge/pinamod-public

WORKDIR /workspace

COPY server.sh ./server.sh

CMD [ "bash", "server.sh" ]
