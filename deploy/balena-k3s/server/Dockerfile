# CPU-only K3s server for balena deployment
#
# References:
# https://k3d.io/v5.7.4/usage/advanced/cuda/#building-a-customized-k3s-image
# https://github.com/k3s-io/k3s/blob/master/package/Dockerfile

FROM ubuntu:22.04

ARG K3S_TAG="v1.28.8+k3s1"

ENV DEBIAN_FRONTEND=noninteractive
ENV K3S_TAG=${K3S_TAG}

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl runc systemd ca-certificates kmod procps gnupg iptables && \
    rm -rf /var/lib/apt/lists/*

RUN curl -sfL https://get.k3s.io | INSTALL_K3S_SKIP_START=true INSTALL_K3S_SKIP_ENABLE=true INSTALL_K3S_VERSION=${K3S_TAG} sh

RUN mkdir -p /opt/groundlight/edge/pinamod-public

WORKDIR /workspace
COPY server.sh ./server.sh

CMD [ "bash", "server.sh" ]
