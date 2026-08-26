#!/bin/bash
# Make sure Docker can pull from cgr.dev/axon.com (required for Dockerfile.fips).
#
# If Docker already can (pull token, prior docker login, or a working cgr cred
# helper), this is a no-op. Do not install a cred helper on top of a pull-token
# login; that hides the token and breaks the next pull.
#
# This script never starts an interactive chainctl SSO. If Docker cannot pull,
# it prints how to log in (laptop: chainctl auth login + configure-docker;
# headless: mint a pull token) and exits. It only runs
# `chainctl auth configure-docker` when chainctl already has a session.
#
# Usage:
#   ./ensure-chainguard-auth.sh

set -euo pipefail

# GNU timeout is missing on stock macOS; gtimeout is coreutils-via-brew.
# No timeout: run unbounded rather than fail with a fake "SSO" error.
TIMEOUT_BIN="$(command -v timeout || command -v gtimeout || true)"
run_bounded() {
    local secs=$1
    shift
    if [ -n "${TIMEOUT_BIN}" ]; then
        "${TIMEOUT_BIN}" -k 2 "${secs}" "$@"
    else
        "$@"
    fi
}

# Prod pin from Dockerfile.fips (ARG PY_FIPS). Manifest inspect only.
_dockerfile="$(readlink -f "$(dirname "$0")/../../Dockerfile.fips")"
_py_fips="$(awk -F= '/^ARG PY_FIPS=/ { print $2; exit }' "${_dockerfile}")"
if [ -z "${_py_fips}" ]; then
    echo "ERROR: could not read ARG PY_FIPS from ${_dockerfile}" >&2
    exit 1
fi
PROBE="${CHAINGUARD_PROBE_IMAGE:-${_py_fips}}"
PULL_TOKEN_PARENT="${CHAINGUARD_PULL_TOKEN_PARENT:-644ce05dcfa4a1ac9e410de97e5b0d7f3194c656}"

# True when Docker can fetch a cgr.dev/axon.com manifest with current credentials.
can_pull_cgr() {
    run_bounded 30 docker buildx imagetools inspect "${PROBE}" >/dev/null 2>&1
}

print_login_help() {
    cat >&2 <<EOF
ERROR: Docker cannot pull ${PROBE}

This script does not start Chainguard SSO. Log in, then re-run.

Headless (this machine): mint a pull token on a laptop that has a browser, then
log Docker in here. If ~/.docker/config.json has credHelpers["cgr.dev"], remove
that entry first so docker login sticks.

  # laptop
  chainctl auth login --org-name axon.com
  chainctl auth pull-token create \\
    --parent ${PULL_TOKEN_PARENT} \\
    --name "ee-fips-local-\$(date +%s)" \\
    --ttl=2h \\
    -o json

  # this machine (identity_id and token from the JSON)
  echo "\$TOKEN" | docker login cgr.dev --username "\$IDENTITY_ID" --password-stdin

Laptop with a browser (SSO, no pull token):

  chainctl auth login --org-name axon.com
  chainctl auth configure-docker

EOF
    if [ "${CI:-}" = "true" ] || [ -n "${GITHUB_ACTIONS:-}" ]; then
        echo "CI: docker login cgr.dev with a pull token before this script. Do not register the cgr cred helper." >&2
    fi
}

echo "Checking whether Docker can pull cgr.dev/axon.com..."
if can_pull_cgr; then
    echo "Docker can already pull cgr.dev/axon.com; leaving existing credentials as-is."
    exit 0
fi

echo "Docker cannot pull cgr.dev/axon.com with current credentials."
run_bounded 30 docker buildx imagetools inspect "${PROBE}" >&2 || true

if [ ! -t 0 ] || [ ! -t 1 ]; then
    print_login_help
    exit 1
fi

if ! command -v chainctl >/dev/null 2>&1; then
    cat >&2 <<'EOF'
ERROR: chainctl not found, and Docker cannot pull cgr.dev/axon.com.

Install chainctl, then re-run this script:
    brew install chainguard-dev/tap/chainctl
    # or https://edu.chainguard.dev/chainguard/chainctl/

Or mint a pull token on another machine and docker login cgr.dev on this one
(see the login instructions in this script).
EOF
    exit 1
fi

echo "Checking chainctl auth status..."
if ! run_bounded 15 chainctl auth status >/dev/null 2>&1; then
    echo "chainctl is not logged in (or auth status timed out)." >&2
    print_login_help
    exit 1
fi

chainctl auth configure-docker

if can_pull_cgr; then
    echo "Chainguard auth OK. Docker can pull cgr.dev/axon.com."
    exit 0
fi

cat >&2 <<EOF
ERROR: chainctl has a session, but Docker still cannot pull ${PROBE}

The cgr cred helper may not be in use. Try: chainctl auth configure-docker
Then: docker buildx imagetools inspect ${PROBE}

Registry error:
EOF
run_bounded 30 docker buildx imagetools inspect "${PROBE}" >&2 || true
exit 1
