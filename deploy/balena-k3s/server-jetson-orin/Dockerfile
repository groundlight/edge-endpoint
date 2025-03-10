# References:
# https://github.com/balena-io-experimental/jetson-sample-new/blob/master/CUDA/Dockerfile.jetson-orin-nano-devkit-nvme
# https://k3d.io/v5.7.4/usage/advanced/cuda/#building-a-customized-k3s-image
# https://github.com/k3s-io/k3s/blob/master/package/Dockerfile

# Using Balena provided Jetson Orin image as base (Ubuntu 22.04)
FROM balenalib/jetson-agx-orin-devkit-ubuntu:jammy-20240401

# Prevent apt-get prompting for input
ENV DEBIAN_FRONTEND noninteractive

RUN echo "deb https://repo.download.nvidia.com/jetson/common r36.3 main" >  /etc/apt/sources.list.d/nvidia.list \
    && echo "deb https://repo.download.nvidia.com/jetson/t234 r36.3 main" >>  /etc/apt/sources.list.d/nvidia.list \
    && apt-key adv --fetch-key http://repo.download.nvidia.com/jetson/jetson-ota-public.asc \
    && mkdir -p /opt/nvidia/l4t-packages/ && touch /opt/nvidia/l4t-packages/.nv-l4t-disable-boot-fw-update-in-preinstall

# Download and install BSP binaries for L4T 36.3 - Jetpack 6
RUN \
    apt-get update && apt-get install -y wget tar lbzip2 binutils xz-utils zstd qemu-user-static cpio git && cd /tmp/ && wget https://developer.nvidia.com/downloads/embedded/l4t/r36_release_v3.0/release/jetson_linux_r36.3.0_aarch64.tbz2 && \
    tar xf jetson_linux_r36.3.0_aarch64.tbz2 && \
    cd Linux_for_Tegra && \
    mkdir -p /tmp/Linux_for_Tegra/rootfs/boot/ && \
    mkdir -p /tmp/Linux_for_Tegra/rootfs/usr/bin && \
    mkdir -p /tmp/Linux_for_Tegra/rootfs/etc && touch /tmp/Linux_for_Tegra/rootfs/etc/resolv.conf && \
    sed -i 's/config.tbz2\"/config.tbz2\" --exclude=etc\/hosts --exclude=etc\/hostname/g' apply_binaries.sh && \
    sed -i 's/CheckPackage qemu-user-static/#CheckPackage qemu-user-static/g' tools/l4t_update_initrd.sh && \
    sed -i 's/trap CleanupVirEnv/#trap CleanupVirEnv/g' tools/l4t_update_initrd.sh&& \
    sed -i 's|cp /usr/bin/qemu-aarch64-static|#cp /usr/bin/qemu-aarch64-static|g' tools/l4t_update_initrd.sh && \
    sed -i 's|^UpdateInitrd|#UpdateInitrd|g' tools/l4t_update_initrd.sh && \
    sed -i 's|^UpdateBackToBaseInitrd|#UpdateBackToBaseInitrd|g' tools/l4t_update_initrd.sh && \
    sed -i 's|cp /etc/resolv.conf|#cp /etc/resolv.conf|g' tools/l4t_update_initrd.sh && \
    sed -i 's|mv "${LDK_ROOTFS_DIR}/etc/resolv.conf"|cp "${LDK_ROOTFS_DIR}/etc/resolv.conf"|g' tools/l4t_update_initrd.sh && \
    sed -i 's|  PrepareVirEnv|#PrepareVirEnv|g' tools/l4t_update_initrd.sh && \
    sed -i 's/install --owner=root --group=root \"${QEMU_BIN}\" \"${L4T_ROOTFS_DIR}\/usr\/bin\/\"/#install --owner=root --group=root \"${QEMU_BIN}\" \"${L4T_ROOTFS_DIR}\/usr\/bin\/\"/g' nv_tegra/nv-apply-debs.sh && \
    sed -i 's/chroot . \//  /g' nv_tegra/nv-apply-debs.sh && \
    cd /tmp/Linux_for_Tegra/ && ./apply_binaries.sh -r / --target-overlay && cd .. && \
    rm -rf Linux_for_Tegra && \
    echo "/usr/lib/aarch64-linux-gnu/tegra" > /etc/ld.so.conf.d/nvidia-tegra.conf && ldconfig

ARG K3S_TAG="v1.28.8+k3s1"
ARG ENABLE_GPU="false"

ENV DEBIAN_FRONTEND noninteractive
ENV K3S_TAG=${K3S_TAG}
ENV ENABLE_GPU=${ENABLE_GPU}

# Install X for GUI support (in case monitor is plugged in)
RUN apt-get install -y --no-install-recommends \
    xserver-xorg-input-evdev \
    xinit \
    x11-xserver-utils \
    dbus-x11 \
    xterm

ENV LD_LIBRARY_PATH=/usr/lib/aarch64-linux-gnu/tegra
ENV UDEV=1

# Prevent screen from turning off
RUN echo "#!/bin/bash" > /etc/X11/xinit/xserverrc \
    && echo "" >> /etc/X11/xinit/xserverrc \
    && echo 'exec /usr/bin/X -s 0 dpms' >> /etc/X11/xinit/xserverrc && \
    echo 'modules=("nvidia_drm"); for module in "${modules[@]}"; do if lsmod | grep -q ${module} ; then echo "Found $module"; rmmod $module; fi; done; startxfce4;' > /opt/startxfce.sh

## If any apt packages install mesa-egl, it will overwrite the tegra-egl
## symlink and ld path, so the following command will ensure tegra-egl remains
## available:
RUN \
    echo "/usr/lib/aarch64-linux-gnu/tegra\n/usr/lib/aarch64-linux-gnu/tegra-egl" \
    > /etc/ld.so.conf.d/000-nvidia-tegra-egl.conf \
    && ldconfig

# Install base dependencies
RUN apt-get update && \
    apt install -y curl runc software-properties-common kmod && \
    rm -rf /var/lib/apt/lists/*

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

# Create a shell script for launching NVIDIA DRM
RUN printf 'modules=("nvidia_drm"); for module in "${modules[@]}"; do if lsmod | grep -q ${module} ; then echo "Found $module"; rmmod $module; fi; done;' > /usr/src/drm-script.sh && chmod +x /usr/src/drm-script.sh

# Set the working directory
WORKDIR /workspace

# Copy the server script into the container
COPY server.sh ./server.sh

# Make the server script executable
RUN chmod +x server.sh

CMD ["/bin/bash", "-c", "/usr/src/drm-script.sh && ./server.sh"]
