#!/bin/bash

set -ex 

cd "$(dirname "$0")"


DATABASE_DIRECTORY="/var/groundlight/sqlite"
DATABASE_PATH="${DATABASE_DIRECTORY}/sqlite.db"
ENTRY_QUERY="CREATE TABLE IF NOT EXISTS test_table (id INTEGER);"
DROP_QUERY="DROP TABLE IF EXISTS test_table;"


reset_tables() {
    TABLES=( "inference_deployments" "image_queries_edge" )

    for TABLE_NAME in "${TABLES[@]}"; do
        if [[ $(sqlite3 "${DATABASE_PATH}" "SELECT name FROM sqlite_master WHERE type='table' AND name='${TABLE_NAME}';") == "${TABLE_NAME}" ]]; then
            echo "${TABLE_NAME} table exists. Deleting records..."
            sqlite3 "${DATABASE_PATH}" "DELETE FROM ${TABLE_NAME};"
        else
            echo "${TABLE_NAME} table doesn't exist."
        fi
    done
}


# Check if we have sqlite3 CLI installed. If not, install it
if [ ! -x "/usr/bin/sqlite3" ]; then
    echo "sqlite3 could not be found. Installing it now..."
    sudo apt-get update
    sudo apt install -y sqlite3

else
    echo "sqlite3 is already installed."
    which sqlite3
fi


# If the database already exists, exit. Otherwise, create it
if [[ -f "${DATABASE_PATH}" ]]; then
    echo "SQLite database file exists and is mounted correctly."
else
    echo "SQLite database file doesn't exist or wasn't mounted correctly. Creating it now..."
    sudo mkdir -p ${DATABASE_DIRECTORY}
    sudo chown -R "$(id -u)":"$(id -g)" "${DATABASE_DIRECTORY}"

    # SQLite is eccentric in a sense that if you just invoke `sqlite3 <db_file>`, it won't 
    # actually create the file. We are using a hack here to initialize the database with 
    # a test table and then drop it. 
    echo "${ENTRY_QUERY}" | sqlite3 "${DATABASE_PATH}"
    echo "${DROP_QUERY}" | sqlite3 "${DATABASE_PATH}"

    # Set journal model to Write-Ahead Logging 
    # echo "PRAGMA journal_mode=WAL;" | sqlite3 "${DATABASE_PATH}"
fi


# Restart tables if the first argument is "restart"
if [ "$1" == "db_reset" ]; then
    echo "Resetting database tables..."
    reset_tables
fi