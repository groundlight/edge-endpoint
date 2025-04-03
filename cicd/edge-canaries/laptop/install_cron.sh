#!/bin/bash

# Get the absolute path of the repo
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="$BASE_DIR/.venv"
ENV_FILE="$BASE_DIR/.env"
PYTHON_SCRIPT="$BASE_DIR/run.py"
CRON_SCRIPT="$BASE_DIR/run_cron.sh"
LOG_FILE="$HOME/canary_logs/laptop_canary.log"

# Required environment variables for this canary
REQUIRED_VARS=(
    "GROUNDLIGHT_API_TOKEN"
    "GROUNDLIGHT_ENDPOINT"
    "RTSP_URL"
    "DETECTOR_ID"
)

# Check if each required environment variable is present
declare -A VAR_VALUES
MISSING_VARS=()
for VAR in "${REQUIRED_VARS[@]}"; do
    VALUE=$(printenv "$VAR")

    if [ -n "$VALUE" ]; then
        VAR_VALUES["$VAR"]="$VALUE"
    else
        MISSING_VARS+=("$VAR")
    fi
done

# Print found environment variables
echo "Found values:"
for VAR in "${!VAR_VALUES[@]}"; do
    echo "$VAR=${VAR_VALUES[$VAR]}"
done
echo ""

# Print missing environment variables
if [ ${#MISSING_VARS[@]} -gt 0 ]; then
    echo "Missing values:"
    for VAR in "${MISSING_VARS[@]}"; do
        echo "$VAR (not set)"
    done
    echo ""

    echo "Please add all required environment variables and then try again."
    exit 1
fi

# Save all values to the ENV_FILE, overwriting previous content
echo "All environment variables are set. Saving environment variables to $ENV_FILE..."
{
    for VAR in "${REQUIRED_VARS[@]}"; do
        # Ensure that double quotes are used correctly without duplication
        echo "$VAR=\"${VAR_VALUES[$VAR]}\""
    done
} > "$ENV_FILE"

# Set up virtual environment
if [ ! -d "$VENV_PATH" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_PATH"
fi

# Activate virtual environment
source "$VENV_PATH/bin/activate"

# Install required dependencies
echo "Installing dependencies..."
pip install -r "$BASE_DIR/requirements.txt" || exit 1

# Ensure run_cron.sh is executable
chmod +x "$CRON_SCRIPT"

# Define the cron job
CRON_JOB="*/5 * * * * $CRON_SCRIPT >> $LOG_FILE 2>&1"

# Install the cron job (prevents duplicates)
(crontab -l 2>/dev/null | grep -v "$CRON_SCRIPT"; echo "$CRON_JOB") | crontab -

# Install the reboot cron job
# TODO figure out why it isn't actually rebooting
# REBOOT_JOB="00 20 * * * echo \"\$(date) - System rebooting via cron\" >> ${LOG_FILE} && /sbin/shutdown -r +1"
# (crontab -l 2>/dev/null | grep -Fv "shutdown -r now"; echo "$REBOOT_JOB") | crontab -

# Install the boot log cron job
BOOT_LOG_JOB="@reboot /bin/bash -c 'echo \"\$(date) - System rebooted\" >> ${LOG_FILE}'"
(crontab -l 2>/dev/null | grep -Fv "System rebooted"; echo "$BOOT_LOG_JOB") | crontab -

echo "Cron job installed successfully! Check logs: $LOG_FILE"
