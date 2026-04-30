# This Dockerfile is used to build the edge-endpoint container image.

# Build args
ARG NGINX_PORT=30101
ARG NGINX_PORT_OLD=6717
ARG UVICORN_PORT=6718
ARG APP_ROOT="/groundlight-edge"
ARG UV_VERSION=0.8.4

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

######################
# React Build Stage
######################
FROM node:20-slim AS react-build-stage
WORKDIR /react-app
COPY app/status_monitor/frontend/package.json app/status_monitor/frontend/package-lock.json ./
RUN npm ci
COPY app/status_monitor/frontend/ ./
RUN npm run build

#############
# Build Stage
#############
FROM python:3.11-slim-bullseye AS production-dependencies-build-stage

# docker buildx will override this for the target platform
ARG TARGETARCH

# Args that are needed in this stage
ARG APP_ROOT

COPY --from=uv /uv /uvx /bin/

# Install required dependencies and tools
# Combine the installations into a single RUN command
# Ensure that we have the bash shell since it doesn't seem to be included in the slim image.
# This is useful for exec'ing into the container for debugging purposes.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    bash \
    curl \
    nginx \
    openssl \
    less \
    unzip \
    sqlite3 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && \
    install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl && \
    rm kubectl

RUN cd /tmp && \
    set -eux; \
    case "$TARGETARCH" in \
    amd64)  UARCH=x86_64 ;; \
    arm64)  UARCH=aarch64 ;; \
    arm)    UARCH=armv7 ;; \
    *) echo "Unsupported arch: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    curl "https://awscli.amazonaws.com/awscli-exe-linux-${UARCH}.zip" -o "awscliv2.zip" && \
    unzip awscliv2.zip && \
    ./aws/install --update && \
    rm -rf awscliv2.zip aws

# Install mount-s3 (Mountpoint for Amazon S3) for FUSE-mounting S3 buckets
# Used by the edge-endpoint init container to mount model weights from S3
RUN set -eux; \
    case "$TARGETARCH" in \
    amd64)  MOUNT_S3_ARCH=x86_64 ;; \
    arm64)  MOUNT_S3_ARCH=arm64 ;; \
    *) echo "Unsupported arch for mount-s3: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://s3.amazonaws.com/mountpoint-s3-release/latest/${MOUNT_S3_ARCH}/mount-s3.deb" -o /tmp/mount-s3.deb && \
    apt-get update && apt-get install -y --no-install-recommends /tmp/mount-s3.deb fuse && \
    rm /tmp/mount-s3.deb && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Set Python and uv ENV vars
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH=${APP_ROOT}/.venv/bin:$PATH

# Copy only required files first to leverage Docker caching
COPY ./pyproject.toml ./uv.lock ${APP_ROOT}/

WORKDIR ${APP_ROOT}

# Install production dependencies only
RUN uv sync --frozen --no-install-project --no-group dev --no-group lint && \
    uv cache clean

# Create /etc/groundlight directory where edge-config.yaml and inference_deployment.yaml will be mounted
RUN mkdir -p /etc/groundlight/edge-config && \
    mkdir -p /etc/groundlight/inference-deployment

# Adding this here for testing purposes. In production, this will be mounted as persistent
# volume in kubernetes
RUN mkdir -p /opt/groundlight/edge/sqlite

# Copy configs
COPY configs ${APP_ROOT}/configs

COPY deploy/k3s/inference_deployment/inference_deployment_template.yaml \
    /etc/groundlight/inference-deployment/


##################
# Production Stage
##################
FROM production-dependencies-build-stage AS production-image

ARG APP_ROOT
ARG NGINX_PORT
ARG UVICORN_PORT

ENV PATH=${APP_ROOT}/.venv/bin:$PATH \
    APP_PORT=${UVICORN_PORT}

WORKDIR ${APP_ROOT}

# Copy the remaining files
COPY /app ${APP_ROOT}/app/

# Copy built React status page assets
COPY --from=react-build-stage /react-app/dist ${APP_ROOT}/app/status_monitor/react-build
COPY /deploy ${APP_ROOT}/deploy/
COPY /licenses ${APP_ROOT}/licenses/
COPY /README.md ${APP_ROOT}/README.md

COPY --from=production-dependencies-build-stage ${APP_ROOT}/configs/nginx.conf /etc/nginx/nginx.conf

# Remove default nginx config
RUN rm /etc/nginx/sites-enabled/default

# Ensure Nginx logs to stdout and stderr
RUN ln -sf /dev/stdout /var/log/nginx/access.log && \
    ln -sf /dev/stderr /var/log/nginx/error.log

CMD ["/bin/bash", "-c", "./app/bin/launch-edge-logic-server.sh"]

# Document the exposed port, which is configured in nginx.conf
EXPOSE ${NGINX_PORT} ${NGINX_PORT_OLD} 443
