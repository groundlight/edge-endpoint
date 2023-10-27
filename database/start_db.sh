#!/bin/sh


DATABASE_DIRECTORY="/var/groundlight/sqlite"
ENTRY_QUERY="CREATE TABLE IF NOT EXISTS test_table (id INTEGER);"
DROP_QUERY="DROP TABLE IF EXISTS test_table;"
SLEEP_TIME=3600

# If the database already exists, exit. Otherwise, create it
if [[ -f "${DATABASE_DIRECTORY}/sqlite.db" ]]; then
    echo "SQLite database file exists and is mounted correctly."
else
    echo "SQLite database file doesn't exist or wasn't mounted correctly. Creating it now..."
    mkdir -p ${DATABASE_DIRECTORY}
    # chown -R "$(id -u)":"$(id -g)" "${DATABASE_DIRECTORY}"
    chmod -R 777 "${DATABASE_DIRECTORY}"
    echo "${ENTRY_QUERY}" | sqlite3 "${DATABASE_DIRECTORY}/sqlite.db"
    echo "${DROP_QUERY}" | sqlite3 "${DATABASE_DIRECTORY}/sqlite.db"
fi

# Loop indefinitely to keep the container running 
while true; do 
    echo "SQLite database is running..."
    sleep ${SLEEP_TIME}
done