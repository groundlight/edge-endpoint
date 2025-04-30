#!/bin/bash

# Part one of getting AWS credentials set up.
# This script runs in a aws-cli container and retrieves the credentials from Janzu.
# Then it uses the credentials to get a login token for ECR.
#
# It saves three files to the shared volume for use by part two:
# 1. /shared/credentials: The AWS credentials file that can be mounted into pods at ~/.aws/credentials
# 2. /shared/token.txt: The ECR login token that can be used to pull images from ECR. This will
#    be used to create a registry secret in k8s.
# 3. /shared/done: A marker file to indicate that the script has completed successfully.

# Note: This script is also used to validate the GROUNDLIGHT_API_TOKEN and GROUNDLIGHT_ENDPOINT
# settings. If you run it with the first argument being "validate", it will only run through the 
# check of the curl results and exit with 0 if they are valid or 1 if they are not. In the latter 
# case, it will also log the results.

if [ "$1" == "validate" ]; then
  echo "Validating GROUNDLIGHT_API_TOKEN and GROUNDLIGHT_ENDPOINT..."
  if [ -z "$GROUNDLIGHT_API_TOKEN" ]; then
    echo "GROUNDLIGHT_API_TOKEN is not set. Exiting."
    exit 1
  fi

  if [ -z "$GROUNDLIGHT_ENDPOINT" ]; then
    echo "GROUNDLIGHT_ENDPOINT is not set. Exiting."
    exit 1
  fi
  validate="yes"
fi

# This function replicates the Groundlight SDK's logic to clean up user-supplied endpoint URLs 
sanitize_endpoint_url() {
    local endpoint="${1:-$GROUNDLIGHT_ENDPOINT}"

    # If empty, set default
    if [[ -z "$endpoint" ]]; then
        endpoint="https://api.groundlight.ai/"
    fi

    # Parse URL scheme and the rest
    if [[ "$endpoint" =~ ^(https?)://([^/]+)(/.*)?$ ]]; then
        scheme="${BASH_REMATCH[1]}"
        netloc="${BASH_REMATCH[2]}"
        path="${BASH_REMATCH[3]}"
    else
        echo "Invalid API endpoint: $endpoint. Must be a valid URL with http or https scheme." >&2
        exit 1
    fi

    # Ensure path is properly initialized
    if [[ -z "$path" ]]; then
        path="/"
    fi

    # Ensure path ends with "/"
    if [[ "${path: -1}" != "/" ]]; then
        path="$path/"
    fi

    # Set default path if just "/"
    if [[ "$path" == "/" ]]; then
        path="/device-api/"
    fi

    # Allow only specific paths
    case "$path" in
        "/device-api/"|"/v1/"|"/v2/"|"/v3/")
            ;;
        *)
            echo "Warning: Configured endpoint $endpoint does not look right - path '$path' seems wrong." >&2
            ;;
    esac

    # Remove trailing slash for output
    sanitized_endpoint="${scheme}://${netloc}${path%/}"
    echo "$sanitized_endpoint"
}

sanitized_url=$(sanitize_endpoint_url "${GROUNDLIGHT_ENDPOINT}")
echo "Sanitized URL: $sanitized_url"

echo "Fetching temporary AWS credentials from Janzu..."
HTTP_STATUS=$(curl -s -L -o /tmp/credentials.json -w "%{http_code}" --fail-with-body --header "x-api-token: ${GROUNDLIGHT_API_TOKEN}" ${sanitized_url}/reader-credentials)

if [ $? -ne 0 ]; then
  echo "Failed to fetch credentials from Janzu"
  if [ -n "$HTTP_STATUS" ]; then
    echo "HTTP Status: $HTTP_STATUS"
  fi
  echo -n "Response:"
  cat /tmp/credentials.json; echo
  exit 1
fi

if [ "$validate" == "yes" ]; then

  echo "API token validation successful. Exiting."
  exit 0
fi

export AWS_ACCESS_KEY_ID=$(sed 's/^.*"access_key_id":"\([^"]*\)".*$/\1/' /tmp/credentials.json)
export AWS_SECRET_ACCESS_KEY=$(sed 's/^.*"secret_access_key":"\([^"]*\)".*$/\1/' /tmp/credentials.json)
export AWS_SESSION_TOKEN=$(sed 's/^.*"session_token":"\([^"]*\)".*$/\1/' /tmp/credentials.json)

cat <<EOF > /shared/credentials
[default]
aws_access_key_id = ${AWS_ACCESS_KEY_ID}
aws_secret_access_key = ${AWS_SECRET_ACCESS_KEY}
aws_session_token = ${AWS_SESSION_TOKEN}
EOF

echo "Credentials fetched and saved to /shared/credentials"
cat /shared/credentials; echo

echo "Fetching AWS ECR login token..."
TOKEN=$(aws ecr get-login-password --region {{ .Values.awsRegion }})
echo $TOKEN > /shared/token.txt

echo "Token fetched and saved to /shared/token.txt"

touch /shared/done
