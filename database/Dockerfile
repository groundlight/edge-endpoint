
ARG ROOT_DIR="/data"
ARG DB_PORT=1433
ARG DB_PATH="/var/groundlight/sqlite"

# use a lightweight Linux distribution as the base image 

FROM alpine:latest 

# Install SQLite 
RUN apk add --no-cache sqlite

# Install python3 and pip 
RUN apk add --no-cache python3 py3-pip

RUN mkdir /var/groundlight 
RUN mkdir /var/groundlight/sqlite 

# Set the working directory to ROOT_DIR
WORKDIR ${ROOT_DIR}

# COPY start.py ${ROOT_DIR}/start.py
COPY start_db.sh ${ROOT_DIR}/start_db.sh
RUN chmod +x ${ROOT_DIR}/start_db.sh 

# Expose the SQLite port 
EXPOSE ${DB_PORT}

ENTRYPOINT ["sh", "start_db.sh"]
