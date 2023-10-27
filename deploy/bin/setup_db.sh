#!/bin/sh

set -ex 

cd "$(dirname "$0")"


DATABASE_DIRECTORY="/var/groundlight/sqlite"
ENTRY_QUERY="CREATE TABLE IF NOT EXISTS test_table (id INTEGER);"
DROP_QUERY="DROP TABLE IF EXISTS test_table;"



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
if [[ -f "${DATABASE_DIRECTORY}/sqlite.db" ]]; then
    echo "SQLite database file exists and is mounted correctly."
else
    echo "SQLite database file doesn't exist or wasn't mounted correctly. Creating it now..."
    sudo mkdir -p ${DATABASE_DIRECTORY}
    sudo chown -R "$(id -u)":"$(id -g)" "${DATABASE_DIRECTORY}"

    # SQLite is eccentric in a sense that if you just invoke `sqlite3 <db_file>`, it won't 
    # actually create the file. We are using a hack here to initialize the database with 
    # a test table and then drop it. 
    # Oddly, running echo ".exit" | sqlite3 <db_file> doesn't work either.
    echo "${ENTRY_QUERY}" | sqlite3 "${DATABASE_DIRECTORY}/sqlite.db"
    echo "${DROP_QUERY}" | sqlite3 "${DATABASE_DIRECTORY}/sqlite.db"
fi
