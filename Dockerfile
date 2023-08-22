# Build args
ARG APP_PORT=6718
ARG APP_ROOT="/groundlight-edge"
ARG POETRY_HOME="/opt/poetry"
ARG POETRY_VERSION=1.5.1

#############
# Build Stage
#############
# Base image
FROM python:3.11-slim-bullseye as production-dependencies-build-stage

# Args that are needed in this stage
ARG APP_ROOT \
    POETRY_HOME \
    POETRY_VERSION

# Install base OS dependencies. 
# We need to install libGL dependencies (`libglib2.0-0` and `libgl1-mesa-lgx`) 
# since they are required by OpenCV 
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y \
    curl \
    nginx \
    libglib2.0-0 \
    libgl1-mesa-glx

# Python environment variables
ENV PYTHONUNBUFFERED=1 \
    # Prevents python creating .pyc files
    PYTHONDONTWRITEBYTECODE=1 \
    # Make poetry install to this location
    POETRY_HOME=${POETRY_HOME} \
    # Poetry version
    POETRY_VERSION=${POETRY_VERSION}

# Install poetry
RUN curl -sSL https://install.python-poetry.org | python -


# Make sure poetry is in the path
ENV PATH=${POETRY_HOME}/bin:$PATH

# Install [tool.poetry.dependencies]
COPY ./pyproject.toml ${APP_ROOT}/

WORKDIR ${APP_ROOT}

# Install production dependencies
RUN poetry install --no-interaction --no-root --without dev


# Copy the configs directory 
COPY configs ${APP_ROOT}/configs 

# Generate NGINX configuration 
RUN poetry run python configs/get_config.py

##################
# Production Stage
##################
FROM production-dependencies-build-stage as production-image

# Args that are needed in this stage
ARG POETRY_HOME \
    APP_ROOT \
    APP_PORT

# Make sure poetry is in the path
ENV PATH=${POETRY_HOME}/bin:$PATH

# Set the working directory
WORKDIR ${APP_ROOT}

# Copy NGINX configuration file from build stage
COPY --from=production-dependencies-build-stage ${APP_ROOT}/configs/nginx.conf /etc/nginx/nginx.conf

COPY /app ${APP_ROOT}/app/

# Remove the default nginx configuration 
RUN rm /etc/nginx/sites-enabled/default

# Run nginx and the application server
ENV APP_PORT=${APP_PORT}
CMD nginx && poetry run uvicorn --workers 1 --host 0.0.0.0 --port ${APP_PORT} --proxy-headers app.main:app

# Document the exposed port which was configured in start_uvicorn.sh
# https://docs.docker.com/engine/reference/builder/#expose
EXPOSE ${APP_PORT}

#########################
# Development Build Stage
#########################
FROM production-dependencies-build-stage as dev-dependencies-build-stage

# Install [tool.poetry.dev-dependencies]
RUN poetry install --no-interaction --no-root

###################
# Development Stage
###################
FROM production-dependencies-build-stage as development-image

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Code reloading
    UVICORN_RELOAD=1 \
    # Enable debug logging
    UVICORN_LOG_LEVEL=debug

WORKDIR ${APP_ROOT}

COPY . ${APP_ROOT}/
