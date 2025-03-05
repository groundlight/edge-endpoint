#!/bin/sh

echo "Fetching temporary AWS credentials from Janzu..."
curl --fail-with-body -sS -L --header "x-api-token: ${GROUNDLIGHT_API_TOKEN}" ${GROUNDLIGHT_ENDPOINT}/device-api/reader-credentials > /tmp/credentials.json

if [ $? -ne 0 ]; then
  echo "Failed to fetch credentials from Janzu"
  echo "Response:"
  cat /tmp/credentials.json; echo
  exit 1
fi


AWS_ACCESS_KEY_ID=$(sed 's/^.*"access_key_id":"\([^"]*\)".*$/\1/' /tmp/credentials.json)
AWS_SECRET_ACCESS_KEY=$(sed 's/^.*"secret_access_key":"\([^"]*\)".*$/\1/' /tmp/credentials.json)
AWS_SESSION_TOKEN=$(sed 's/^.*"session_token":"\([^"]*\)".*$/\1/' /tmp/credentials.json)

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
