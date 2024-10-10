#!/bin/bash

# Set up the SQLite database for the edge endpoint.
# This script is invoked by an initContainer in the edge endpoint deployment.

set -ex

DATABASE_DIRECTORY="/opt/groundlight/edge/sqlite"
DATABASE_PATH="${DATABASE_DIRECTORY}/sqlite.db"
ENTRY_QUERY="CREATE TABLE IF NOT EXISTS test_table (id INTEGER);"
DROP_QUERY="DROP TABLE IF EXISTS test_table;"

echo "Using sqlite3 from $(which sqlite3)"

# Always remove the existing database file
if [[ -f "${DATABASE_PATH}" ]]; then
    echo "Removing existing SQLite database file..."
    rm -f "${DATABASE_PATH}"
fi

# Create the database directory if it doesn't exist
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

echo "SQLite database has been created."