!/bin/bash

# Sets up the SQLite database for the edge endpoint.
# Expects the following environment variables:
# - DB_RESET: If set to 1, will delete all the data in the database.
#
# This script is invoked by an initContainer in the edge endpoint deployment.

set -ex 

DB_RESET=${DB_RESET:-0}

DATABASE_DIRECTORY="/opt/groundlight/edge/sqlite"
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

echo "Using sqlite3 from $(which sqlite3)"


# If the database already exists, exit. Otherwise, create it
if [[ -f "${DATABASE_PATH}" ]]; then
    echo "SQLite database file exists and is mounted correctly."
else
    echo "SQLite database file doesn't exist or wasn't mounted correctly. Creating it now..."
    mkdir -p ${DATABASE_DIRECTORY}
    chown -R "$(id -u)":"$(id -g)" "${DATABASE_DIRECTORY}"

    # SQLite is eccentric in a sense that if you just invoke `sqlite3 <db_file>`, it won't 
    # actually create the file. We are using a hack here to initialize the database with 
    # a test table and then drop it. 
    echo "${ENTRY_QUERY}" | sqlite3 "${DATABASE_PATH}"
    echo "${DROP_QUERY}" | sqlite3 "${DATABASE_PATH}"

    # Set journal mode to Write-Ahead Logging. This makes it much faster, at the risk of 
    # possibly losing data if the machine crashes suddenly.
    # https://www.sqlite.org/wal.html
    echo "PRAGMA journal_mode=WAL;" | sqlite3 "${DATABASE_PATH}"
fi

if [[ "${DB_RESET}" == "1" ]]; then
    echo "Resetting tables..."
    reset_tables
fi