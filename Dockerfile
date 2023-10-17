# Build args
ARG APP_PORT=6718
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
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       bash \
       curl \
       nginx \
       libglib2.0-0 \
       libgl1-mesa-glx \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && curl -sSL https://install.python-poetry.org | python -

# Set Python and Poetry ENV vars
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POETRY_HOME=${POETRY_HOME} \
    POETRY_VERSION=${POETRY_VERSION} \
    PATH=${POETRY_HOME}/bin:$PATH

# Copy only required files first to leverage Docker caching
COPY ./pyproject.toml ${APP_ROOT}/

WORKDIR ${APP_ROOT}

# Install production dependencies only
RUN poetry install --no-interaction --no-root --without dev && \
    poetry cache clear --all pypi

# Create /etc/groundlight directory where edge-config.yaml and inference_deployment.yaml will be mounted
RUN mkdir /etc/groundlight

RUN mkdir /etc/groundlight/edge-config && \
    mkdir /etc/groundlight/inference-deployment
# Copy configs
COPY configs ${APP_ROOT}/configs

RUN mkdir /etc/nginx/ssl 
# COPY certificates/nginx_ed25519.key /etc/nginx/ssl/nginx_ed25519.key
# COPY certificates/nginx_ed25519.crt /etc/nginx/ssl/nginx_ed25519.crt

# Copy the SSL key and certificate into their respective files only 
# if they are provided. 
# RUN if [ ! -z "${SSL_PRIVATE_KEY}" ]; then \
#         echo "${SSL_PRIVATE_KEY}" > /etc/nginx/ssl/nginx_ed25519.key; \
#         chown root:root /etc/nginx/ssl/nginx_ed25519.key; \
#         chmod 600 /etc/nginx/ssl/nginx_ed25519.key; \
#     fi && \
#     if [ ! -z "${SSL_CERT}" ]; then \
#         echo "${SSL_CERT}" > /etc/nginx/ssl/nginx_ed25519.crt; \
#         chown root:root /etc/nginx/ssl/nginx_ed25519.crt; \
#         chmod 600 /etc/nginx/ssl/nginx_ed25519.crt; \
#     fi

COPY $SSL_PRIVATE_KEY /etc/nginx/ssl/nginx_ed25519.key
COPY $SSL_CERT /etc/nginx/ssl/nginx_ed25519.crt
RUN chown root:root /etc/nginx/ssl/nginx_ed25519.key && 
    chmod 600 /etc/nginx/ssl/nginx_ed25519.key && 
    chown root:root /etc/nginx/ssl/nginx_ed25519.crt && 
    chmod 600 /etc/nginx/ssl/nginx_ed25519.crt

COPY deploy/k3s/inference_deployment/inference_deployment_template.yaml \
    /etc/groundlight/inference-deployment/


##################
# Production Stage
##################
FROM production-dependencies-build-stage as production-image

ARG APP_ROOT
ARG APP_PORT

ENV PATH=${POETRY_HOME}/bin:$PATH \
    APP_PORT=${APP_PORT}

WORKDIR ${APP_ROOT}

# Copy the remaining files
COPY /app ${APP_ROOT}/app/

COPY --from=production-dependencies-build-stage ${APP_ROOT}/configs/nginx.conf /etc/nginx/nginx.conf
COPY --from=production-dependencies-build-stage /etc/nginx/ssl /etc/nginx/ssl

# Update certificates
RUN update-ca-certificates

# Remove default nginx config
RUN rm /etc/nginx/sites-enabled/default

CMD nginx && poetry run uvicorn --workers 1 --host 0.0.0.0 --port ${APP_PORT} --proxy-headers app.main:app

# Document the exposed port which was configured in start_uvicorn.sh
# https://docs.docker.com/engine/reference/builder/#expose
EXPOSE ${APP_PORT}
