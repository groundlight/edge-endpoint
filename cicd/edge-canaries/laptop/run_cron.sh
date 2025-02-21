#!/bin/bash

# Get the absolute path of the repo
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PATH="$BASE_DIR/laptop/.venv"
PYTHON_SCRIPT="$BASE_DIR/laptop/run.py"
LOG_FILE="$HOME/canary_logs/laptop_canary.log"
ENV_FILE="$BASE_DIR/laptop/.env"

# Load environment variables from .env
if [ -f "$ENV_FILE" ]; then
    export $(grep -v '^#' "$ENV_FILE" | xargs)
else
    echo "ERROR: .env file not found! Exiting..." >> "$LOG_FILE" 2>&1
    exit 1
fi

# Activate virtual environment
source "$VENV_PATH/bin/activate"

# Make sure log file exists
mkdir -p "$(dirname "$LOG_FILE")" && touch "$LOG_FILE"

# Log execution info (for debugging)
echo "----------------------------" >> "$LOG_FILE" 2>&1
echo "Cron job started at $(date)" >> "$LOG_FILE" 2>&1
echo "Using Python: $(which python3)" >> "$LOG_FILE" 2>&1

# Run the python script and log output to LOG_FILE
# Redirect any logs from OpenCV that contain "[h264 @" because they will clutter the logs
python3 "$PYTHON_SCRIPT" 2> >(stdbuf -oL grep -vE "\[h264 @" >> "$LOG_FILE") >> "$LOG_FILE"

echo "Cron job finished at $(date)" >> "$LOG_FILE" 2>&1
