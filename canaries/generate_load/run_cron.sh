#!/bin/bash

# Get the absolute path of the repo
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PATH="$BASE_DIR/.venv"
PYTHON_SCRIPT="$BASE_DIR/generate_load/run.py"
LOG_FILE="$HOME/canary_logs/generate_load_cron.log"
ENV_FILE="$BASE_DIR/.env"

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
echo "GROUNDLIGHT_API_TOKEN is set? ${GROUNDLIGHT_API_TOKEN:+YES}" >> "$LOG_FILE" 2>&1

# Run the Python script
python3 "$PYTHON_SCRIPT" >> "$LOG_FILE" 2>&1

echo "Cron job finished at $(date)" >> "$LOG_FILE" 2>&1
