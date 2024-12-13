# References:
# https://k3d.io/v5.7.4/usage/advanced/cuda/#building-a-customized-k3s-image
# https://github.com/k3s-io/k3s/blob/master/package/Dockerfile

# Use this instead of, for example, balenalib/genericx86-64-ext-ubuntu:focal, because
# it is cross-platform and can be used on any architecture / type of device.
FROM ubuntu:22.04

ARG K3S_TAG="v1.28.8+k3s1"
ARG NVIDIA_DRIVER_MAJOR_VERSION="550"
ARG ENABLE_GPU="false"

ENV DEBIAN_FRONTEND noninteractive
ENV K3S_TAG=${K3S_TAG}
ENV NVIDIA_DRIVER_MAJOR_VERSION=${NVIDIA_DRIVER_MAJOR_VERSION}
ENV ENABLE_GPU=${ENABLE_GPU}
ENV NVIDIA_DRIVER_VERSION="550.127.05"

# Install base dependencies
RUN apt-get update && \
    apt install -y curl runc software-properties-common kmod && \
    rm -rf /var/lib/apt/lists/*

# Install Nvidia driver only if GPU is enabled. Must match version in gpu container exactly
# NOTE: sometimes this reposotory bumps the driver version accessed here and then things
# stop working (no nvidia-smi in the server). If that happens, you can find the latest
# driver version at https://www.nvidia.com/en-us/drivers/unix/ and update the version
# in the gpu Dockerfile.
RUN if [ "$ENABLE_GPU" = "true" ]; then \
        # add-apt-repository ppa:graphics-drivers/ppa && \
        # apt update && \
        # apt install -y nvidia-driver-${NVIDIA_DRIVER_MAJOR_VERSION} && \
        # rm -rf /var/lib/apt/lists/*; \
        # Download the specific driver from NVIDIA (replace with actual URL)
        curl -O https://us.download.nvidia.com/XFree86/Linux-x86_64/${NVIDIA_DRIVER_VERSION}/NVIDIA-Linux-x86_64-${NVIDIA_DRIVER_VERSION}.run && \
        chmod +x NVIDIA-Linux-x86_64-${NVIDIA_DRIVER_VERSION}.run && \
        # Install the driver with minimal options
        ./NVIDIA-Linux-x86_64-${NVIDIA_DRIVER_VERSION}.run \
          --ui=none \
          --no-questions \
          --no-drm \
          --no-x-check \
          --no-systemd \
          --no-kernel-module \
          --no-distro-scripts \
          --no-nouveau-check \
          --no-rpms \
          --no-backup \
          --no-abi-note \
          --no-check-for-alternate-installs \
          --no-libglx-indirect && \
        rm NVIDIA-Linux-x86_64-${NVIDIA_DRIVER_VERSION}.run; \
    fi

# Install K3s binary (also installs containerd - must be done before installing nvidia-container-toolkit)
RUN curl -sfL https://get.k3s.io | INSTALL_K3S_SKIP_START=true INSTALL_K3S_SKIP_ENABLE=true INSTALL_K3S_VERSION=${K3S_TAG} sh

# Install the NVIDIA container toolkit only if GPU is enabled
RUN if [ "$ENABLE_GPU" = "true" ]; then \
        curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg && \
        curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
        sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
        tee /etc/apt/sources.list.d/nvidia-container-toolkit.list && \
        apt-get update && \
        apt-get install -y nvidia-container-toolkit && \
        rm -rf /var/lib/apt/lists/* && \
        nvidia-ctk runtime configure --runtime=containerd; \
    fi

# Add nvidia-gpu-operator manifest
COPY manifests/nvidia-gpu-operator.yaml /opt/k3s/manifests/

# Make pinamod-public directory for hostmapped volume
RUN mkdir -p /opt/groundlight/edge/pinamod-public

WORKDIR /workspace

COPY server.sh ./server.sh

CMD [ "bash", "server.sh" ]
