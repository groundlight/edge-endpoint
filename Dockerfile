# Use Python 3.11, Debian Bullseye (v11), and the slim image
FROM python:3.11-slim-bullseye

# Package metadata
LABEL maintainer="Groundlight <support@groundlight.ai>"

# Update the OS packages for security patches
RUN apt-get update \
    && apt-get upgrade -y

RUN python --version
