# https://github.com/balena-io-experimental/balena-k3s/blob/main/bastion/Dockerfile
# ------- Build Stage -------
FROM golang:1.21.0 AS arkade

WORKDIR /src

ARG ARKADE_VERSION=0.10.1
ARG CGO_ENABLED=0

ADD https://github.com/alexellis/arkade/archive/refs/tags/${ARKADE_VERSION}.tar.gz ./

RUN tar xvf ${ARKADE_VERSION}.tar.gz --strip-components=1 && make build

# ------- Runtime Stage -------
FROM debian:bullseye-slim

WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install --no-install-recommends -y \
    ca-certificates \
    curl \
    unzip \
    dnsutils \
    vim \
    jq \
    bash-completion \
    gettext-base \
    procps \
    htop && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Note that currently this is only for ARM
RUN curl "https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip" -o "awscliv2.zip"
RUN unzip awscliv2.zip && rm awscliv2.zip
RUN ./aws/install
RUN aws --version

COPY --from=arkade /src/arkade /usr/local/bin/arkade

ENV PATH "${PATH}:/root/.arkade/bin/"

RUN arkade version && \
    arkade get --progress=false \
    flux@v0.39.0 \
    helm@v3.11.1 \
    k3sup@0.12.12 \
    k9s@v0.27.2 \
    kubectl@v1.26.2


# Copy edge-endpoint to /app/edge-endpoint
RUN mkdir -p /app/edge-endpoint
COPY . /app/edge-endpoint

RUN echo "source /app/edge-endpoint/deploy/balena-k3s/bastion/src/kube-bash.sh" >> /root/.bashrc
RUN chmod +x ./edge-endpoint/deploy/bin/setup-ee.sh

ENTRYPOINT []
CMD ["/bin/sh", "-c", "./edge-endpoint/deploy/bin/setup-ee.sh && tail -f /dev/null"]
