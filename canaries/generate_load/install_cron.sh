#!/bin/bash

# Get the absolute path of the repo
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PATH="$BASE_DIR/.venv"
ENV_FILE="$BASE_DIR/.env"
PYTHON_SCRIPT="$BASE_DIR/generate_load/run.py"
CRON_SCRIPT="$BASE_DIR/generate_load/run_cron.sh"
LOG_FILE="$HOME/canary_logs/generate_load_cron.log"

# Ensure .env file exists
if [ ! -f "$ENV_FILE" ]; then
    echo ".env file not found! Creating a default one..."
    cat <<EOF > "$ENV_FILE"
GROUNDLIGHT_API_TOKEN="api_xxxxxx"
GROUNDLIGHT_ENDPOINT="http://localhost:30101"
RTSP_URL="rtsp://..."
EOF
    echo "Default .env file created at: $ENV_FILE"
    echo "Please edit this file with your actual values before running this script again."
    exit 1
fi

# Set up virtual environment
if [ ! -d "$VENV_PATH" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_PATH"
fi

# Activate virtual environment
source "$VENV_PATH/bin/activate"

# Install required dependencies
echo "Installing dependencies..."
pip install -r "$BASE_DIR/requirements.txt"

# Ensure run_cron.sh is executable
chmod +x "$CRON_SCRIPT"

# Define the cron job
CRON_JOB="*/5 * * * * $CRON_SCRIPT >> $LOG_FILE 2>&1"

# Install the cron job (prevents duplicates)
(crontab -l 2>/dev/null | grep -v "$CRON_SCRIPT"; echo "$CRON_JOB") | crontab -

echo "Cron job installed successfully! Check logs: $LOG_FILE"
