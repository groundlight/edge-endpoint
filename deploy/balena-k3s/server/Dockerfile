# CPU-only K3s server for balena deployment
#
# References:
# https://k3d.io/v5.7.4/usage/advanced/cuda/#building-a-customized-k3s-image
# https://github.com/k3s-io/k3s/blob/master/package/Dockerfile

# -------------------------
# Stage 1: Preload - download third-party images as tarballs for airgap/restricted network support
# NOTE: Keep the preloaded image list in sync across Dockerfile, Dockerfile.gpu, and Dockerfile.jetson
# -------------------------
FROM alpine:3.20 AS preloader
ARG K3S_TAG="v1.28.8+k3s1"

# Install crane for pulling container images without a Docker daemon
# Detect architecture via uname -m since Balena's legacy builder doesn't set TARGETARCH
RUN apk add --no-cache curl tar && \
    ARCH=$(uname -m) && \
    if [ "$ARCH" = "aarch64" ]; then CRANE_ARCH="arm64"; else CRANE_ARCH="x86_64"; fi && \
    curl -sL "https://github.com/google/go-containerregistry/releases/latest/download/go-containerregistry_Linux_${CRANE_ARCH}.tar.gz" | \
    tar -xzf - -C /usr/local/bin crane

# Download k3s airgap images (contains coredns, metrics-server, local-path-provisioner, etc.)
# Note: k3s tags use '+' which is invalid in OCI references, so we replace with '-'
RUN mkdir -p /preload && \
    ARCH=$(uname -m) && \
    if [ "$ARCH" = "aarch64" ]; then K3S_ARCH="arm64"; else K3S_ARCH="amd64"; fi && \
    K3S_REF=$(echo "${K3S_TAG}" | sed 's/+/-/g') && \
    crane export --platform "linux/${K3S_ARCH}" "docker.io/rancher/k3s:${K3S_REF}" - | tar -xf - -C /tmp bin/aux/k3s-airgap-images.tar.zst 2>/dev/null && \
    mv /tmp/bin/aux/k3s-airgap-images.tar.zst /preload/ || \
    echo "WARNING: Could not extract airgap images from k3s image, will download from GitHub" && \
    K3S_VERSION=$(echo ${K3S_TAG} | sed 's/+/%2B/g') && \
    wget -q "https://github.com/k3s-io/k3s/releases/download/${K3S_VERSION}/k3s-airgap-images-${K3S_ARCH}.tar.zst" \
        -O /preload/k3s-airgap-images.tar.zst || true

# Download app utility images used by the Helm chart
RUN ARCH=$(uname -m) && \
    if [ "$ARCH" = "aarch64" ]; then PLAT="linux/arm64"; else PLAT="linux/amd64"; fi && \
    crane pull --platform "$PLAT" docker.io/amazon/aws-cli:latest /preload/aws-cli-latest.tar && \
    crane pull --platform "$PLAT" docker.io/bitnami/kubectl:latest /preload/kubectl-latest.tar && \
    crane pull --platform "$PLAT" docker.io/alpine:3.20 /preload/alpine-3.20.tar && \
    crane pull --platform "$PLAT" docker.io/busybox:1.36 /preload/busybox-1.36.tar

# -------------------------
# Stage 2: K3s server
# -------------------------
FROM ubuntu:22.04

ARG K3S_TAG="v1.28.8+k3s1"

ENV DEBIAN_FRONTEND=noninteractive
ENV K3S_TAG=${K3S_TAG}

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl runc systemd ca-certificates kmod procps gnupg iptables && \
    rm -rf /var/lib/apt/lists/*

RUN curl -sfL https://get.k3s.io | INSTALL_K3S_SKIP_START=true INSTALL_K3S_SKIP_ENABLE=true INSTALL_K3S_VERSION=${K3S_TAG} sh

# Copy preloaded images for airgap/restricted network support
COPY --from=preloader /preload/ /opt/k3s/preload-images/

RUN mkdir -p /opt/groundlight/edge/pinamod-public

WORKDIR /workspace
COPY server.sh ./server.sh

CMD [ "bash", "server.sh" ]
