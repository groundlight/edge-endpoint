#!/bin/bash

set -x

aws secretsmanager get-secret-value --secret-id "ghar2eeut-private-key" | jq .SecretString -r > ~/.ssh/ghar2eeut.pem
chmod 600 ~/.ssh/ghar2eeut.pem

EEUT_IP=$(pulumi stack output eeut_private_ip)

ssh -i ~/.ssh/ghar2eeut.pem ubuntu@$EEUT_IP

