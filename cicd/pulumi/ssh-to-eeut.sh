#!/bin/bash
# This is an odd script.  It will only work from the GHA runner.
# and it expects to have access to the pulumi stack here.  Which means
# to use it you'd have to log into the runner and clone the EE repo.
# But if that's what you need to do, this will help.

# Alternately, you can use this from a workstation that has pulumi access,
# but not network access, and define the proxy host in the EEUT_PROXY_HOST
# variable.  Or you might set the EEUT_PROXY_HOST with an IP address and an SSH key like 
# export EEUT_PROXY_HOST="1.2.3.4 -i ~/.ssh/runner-admin.pem"

set -x

if [ ! -f ~/.ssh/ghar2eeut.pem ]; then  
  aws secretsmanager get-secret-value --secret-id "ghar2eeut-private-key" | jq .SecretString -r > ~/.ssh/ghar2eeut.pem
  chmod 600 ~/.ssh/ghar2eeut.pem
fi

EEUT_IP=$(pulumi stack output eeut_private_ip)

if [ -n "$EEUT_PROXY_HOST" ]; then
    PROXY_COMMAND=(-o ProxyCommand="ssh -W %h:%p ubuntu@$EEUT_PROXY_HOST")
else
    PROXY_COMMAND=()
fi

ssh -i ~/.ssh/ghar2eeut.pem "${PROXY_COMMAND[@]}" ubuntu@$EEUT_IP

