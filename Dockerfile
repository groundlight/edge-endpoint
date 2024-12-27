# Build args
ARG NGINX_PORT=30101
ARG NGINX_PORT_OLD=6717
ARG UVICORN_PORT=6718
ARG APP_ROOT="/groundlight-edge"
ARG POETRY_HOME="/opt/poetry"
ARG POETRY_VERSION=1.5.1

#############
# Build Stage
#############
FROM python:3.11-slim-bullseye as production-dependencies-build-stage

# Args that are needed in this stage
ARG APP_ROOT
ARG POETRY_HOME
ARG POETRY_VERSION

# Install required dependencies and tools
# Combine the installations into a single RUN command
# Ensure that we have the bash shell since it doesn't seem to be included in the slim image.
# This is useful for exec'ing into the container for debugging purposes.
# We need to install libGL dependencies (`libglib2.0-0` and `libgl1-mesa-lgx`)
# since they are required by OpenCV
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    bash \
    curl \
    nginx \
    libglib2.0-0 \
    libgl1-mesa-glx \
    sqlite3 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    curl -sSL https://install.python-poetry.org | python -

# Set Python and Poetry ENV vars
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POETRY_HOME=${POETRY_HOME} \
    POETRY_VERSION=${POETRY_VERSION} \
    PATH=${POETRY_HOME}/bin:$PATH

# Copy only required files first to leverage Docker caching
COPY ./pyproject.toml ./poetry.lock ${APP_ROOT}/

WORKDIR ${APP_ROOT}

# Install production dependencies only
RUN poetry install --no-interaction --no-root --without dev --without lint && \
    poetry cache clear --all pypi

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
FROM production-dependencies-build-stage as production-image

ARG APP_ROOT
ARG NGINX_PORT
ARG UVICORN_PORT

ENV PATH=${POETRY_HOME}/bin:$PATH \
    APP_PORT=${UVICORN_PORT}

WORKDIR ${APP_ROOT}

# Copy the remaining files
COPY /app ${APP_ROOT}/app/

COPY --from=production-dependencies-build-stage ${APP_ROOT}/configs/nginx.conf /etc/nginx/nginx.conf

# Remove default nginx config
RUN rm /etc/nginx/sites-enabled/default

# Ensure Nginx logs to stdout and stderr
RUN ln -sf /dev/stdout /var/log/nginx/access.log && \
    ln -sf /dev/stderr /var/log/nginx/error.log

CMD nginx && poetry run uvicorn --workers 8 --host 0.0.0.0 --port ${APP_PORT} --proxy-headers app.main:app

# Document the exposed port, which is configured in nginx.conf
EXPOSE ${NGINX_PORT} ${NGINX_PORT_OLD}
