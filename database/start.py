import subprocess
import logging
import time
import sqlite3

DATABASE_PATH = "/var/groundlight/sqlite/sqlite.db"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    while True:
        logging.info("Attempting to start sqlite3 database")
        try:
            subprocess.run(["sqlite3", DATABASE_PATH])

        except Exception as e:
            logging.info(f"Failed to start database", exc_info=True)

        time.sleep(30)
