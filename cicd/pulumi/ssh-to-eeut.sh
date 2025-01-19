#!/bin/bash
# This is an odd script.  It will only work from the GHA runner.
# and it expects to have access to the pulumi stack here.  Which means
# to use it you'd have to log into the runner and clone the EE repo.
# But if that's what you need to do, this will help.

set -x

aws secretsmanager get-secret-value --secret-id "ghar2eeut-private-key" | jq .SecretString -r > ~/.ssh/ghar2eeut.pem
chmod 600 ~/.ssh/ghar2eeut.pem

EEUT_IP=$(pulumi stack output eeut_private_ip)

ssh -i ~/.ssh/ghar2eeut.pem ubuntu@$EEUT_IP

