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
RUN poetry install --no-interaction --no-root --without dev 

# Create /etc/groundlight directory where edge-config.yaml will be mounted 
RUN mkdir /etc/groundlight

# Copy configs
COPY configs ${APP_ROOT}/configs 

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

# Remove default nginx config
RUN rm /etc/nginx/sites-enabled/default

CMD nginx && poetry run uvicorn --workers 1 --host 0.0.0.0 --port ${APP_PORT} --proxy-headers app.main:app

# Document the exposed port which was configured in start_uvicorn.sh
# https://docs.docker.com/engine/reference/builder/#expose
EXPOSE ${APP_PORT}

#########################
# Development Build Stage
#########################
FROM production-dependencies-build-stage as dev-dependencies-build-stage

RUN poetry install --no-interaction --no-root

###################
# Development Stage
###################
FROM production-dependencies-build-stage as development-image

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UVICORN_RELOAD=1 \
    UVICORN_LOG_LEVEL=debug

WORKDIR ${APP_ROOT}

# Copy all files for development
COPY . ${APP_ROOT}/
