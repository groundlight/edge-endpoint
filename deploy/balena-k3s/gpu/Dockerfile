# Balena support for CUDA on an Nvidia GPU in an x86 device
# Based on https://github.com/balena-io-examples/nvidia-x86
#
# This page gives a good overview of what is happening here:
# https://blog.balena.io/how-to-use-nvidia-gpu-on-x86-device-balenaos/
#
# TLDR: This Dockerfile downloads the Nvidia driver and kernel source for the device
# and compiles the Nvidia driver kernel module. `entry.sh` is then run to load the
# kernel module (via insmod). This is necessary because the host device's BalenaOS is
# read-only, so the Nvidia driver cannot be installed on the host OS.

FROM balenalib/genericx86-64-ext:bullseye-run-20211030

WORKDIR /usr/src

ENV DEBIAN_FRONTEND noninteractive

# Set some variables for the kernel source and NVIDIA driver
# See https://github.com/balena-io-examples/nvidia-x86/tree/master?tab=readme-ov-file#gpu-container
# for instructions on how to set these variables. THEY ARE IMPORTANT!
ENV VERSION="6.0.24%2Brev1"

# NOTE: this does not support generic-aarch64 devices
ENV BALENA_MACHINE_NAME="generic-amd64"
ENV YOCTO_VERSION=6.6.23
ENV YOCTO_KERNEL=${YOCTO_VERSION}-yocto-standard
ENV NVIDIA_DRIVER_VERSION=550.127.05
ENV NVIDIA_DRIVER=NVIDIA-Linux-x86_64-${NVIDIA_DRIVER_VERSION}

# Install some prereqs
RUN install_packages git wget unzip build-essential libelf-dev bc libssl-dev bison flex software-properties-common

WORKDIR /usr/src/kernel_source

# Causes a pipeline to produce a failure return code if any command errors.
# Normally, pipelines only return a failure if the last command errors.
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Download the kernel source then prepare kernel source to build a module.
RUN \
    [ "${VERSION%%.*}" -gt "2" ] && FILE_NAME="kernel_modules_headers.tar.gz" || FILE_NAME="kernel_source.tar.gz" && \
    curl -fsSL "https://files.balena-cloud.com/images/${BALENA_MACHINE_NAME}/${VERSION}/${FILE_NAME}" \
    | tar xz --strip-components=2 && \
        make -C build modules_prepare -j"$(nproc)"

# required if using install-libglvnd from nvidia-installer below
RUN install_packages libglvnd-dev

WORKDIR /usr/src/nvidia

# Download and compile NVIDIA driver
RUN \
    curl -fsSL -O https://us.download.nvidia.com/XFree86/Linux-x86_64/$NVIDIA_DRIVER_VERSION/$NVIDIA_DRIVER.run && \
    chmod +x ./${NVIDIA_DRIVER}.run && \
    ./${NVIDIA_DRIVER}.run --extract-only && \
    # Install userspace portion, needed if container will also have CUDA etc...
    # Not needed if just building kernel module.
    # Do include in any application container.
    ./${NVIDIA_DRIVER}/nvidia-installer \
    --ui=none \
    --no-questions \
    --no-drm \
    --no-x-check \
    --no-systemd \
    --no-kernel-module \
    --no-distro-scripts \
    --install-compat32-libs \
    --no-nouveau-check \
    --no-rpms \
    --no-backup \
    --no-abi-note \
    --no-check-for-alternate-installs \
    --no-libglx-indirect \
    --install-libglvnd \
    --x-prefix=/tmp/null \
    --x-module-path=/tmp/null \
    --x-library-path=/tmp/null \
    --x-sysconfig-path=/tmp/null \
    --kernel-name=${YOCTO_KERNEL} \
    --skip-depmod \
    --expert && \
    make -C ${NVIDIA_DRIVER}/kernel KERNEL_MODLIB=/usr/src/kernel_source IGNORE_CC_MISMATCH=1 modules

WORKDIR /nvidia/driver

RUN find /usr/src/nvidia/${NVIDIA_DRIVER}/kernel -name "*.ko" -exec mv {} . \;

WORKDIR /usr/src/app
COPY *.sh ./

ENTRYPOINT ["/bin/bash", "/usr/src/app/entry.sh"]