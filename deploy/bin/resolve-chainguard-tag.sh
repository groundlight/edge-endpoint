#!/bin/bash
# Resolve the newest date-stamped tag (and its digest) for a Chainguard repo.
#
# Usage:
#   ./resolve-chainguard-tag.sh <repo> <stream>
#
#   repo    Chainguard repo name, e.g. python-fips
#   stream  Tag stream without the datestamp, e.g. 3.11 or 3.11-dev
#
# Example:
#   ./resolve-chainguard-tag.sh python-fips 3.11-dev
#   cgr.dev/axon.com/python-fips:3.11-dev-202607280707@sha256:de80b7e8...
#
# WHY THIS EXISTS
#
# Never pin a Chainguard image by its mutable tag. In cgr.dev/axon.com the mutable tags
# (:latest, :3.11) are ~11 months stale -- python-fips:3.11 was built 2025-08-22 while the
# date-stamped builds are current. Two consequences:
#
#   1. A mutable tag ships a year of unpatched CVEs, which is the opposite of the point.
#   2. Worse, it silently breaks FIPS: the stale image carries libcrypto3 3.5.2-r1 while the
#      apk repo it points at serves 3.6.3-r3, so any `apk add` in a build upgrades libcrypto
#      out from under openssl-config-fipshardened and the FIPS provider. The image still says
#      -fips but no longer is.
#
# `chainctl images tags list` is no help here: it reports only mutable tags, which makes most
# of the catalog look empty. This queries the registry API directly. Note tags/list caps at
# 1000 entries per page, so pagination via `last=` is required -- python-fips alone has 61k
# tags.

set -euo pipefail

REPO="${1:-}"
STREAM="${2:-}"
ORG="${CHAINGUARD_ORG:-axon.com}"

if [ -z "$REPO" ] || [ -z "$STREAM" ]; then
    echo "Usage: $0 <repo> <stream>" >&2
    echo "Example: $0 python-fips 3.11-dev" >&2
    exit 1
fi

if ! command -v chainctl >/dev/null 2>&1; then
    echo "ERROR: chainctl not found. Install it and run 'chainctl auth login'." >&2
    exit 1
fi

# Keep stderr: when this fails it is usually an expired session, and the chainctl message
# says so far more usefully than any wrapper text could.
if ! TOKEN=$(chainctl auth token --audience cgr.dev); then
    echo "ERROR: could not mint a cgr.dev token (see the chainctl error above)." >&2
    echo "       Try 'chainctl auth login'." >&2
    exit 1
fi
if [ -z "$TOKEN" ]; then
    echo "ERROR: chainctl returned an empty cgr.dev token. Try 'chainctl auth login'." >&2
    exit 1
fi

newest=""
last=""
while :; do
    url="https://cgr.dev/v2/${ORG}/${REPO}/tags/list?n=1000"
    [ -n "$last" ] && url="${url}&last=${last}"

    # Distinguish "the registry returned no more tags" from "the request failed". Without
    # this, an auth or network error looks identical to an exhausted listing and surfaces as
    # the misleading "no date-stamped tags found" error at the end.
    if ! response=$(curl -sf -H "Authorization: Bearer ${TOKEN}" "$url"); then
        echo "ERROR: request to ${url} failed (auth expired, or no access to ${ORG}/${REPO})." >&2
        exit 1
    fi

    tags=$(echo "$response" | python3 -c "import json,sys; print('\n'.join(json.load(sys.stdin).get('tags') or []))")

    if [ -z "$tags" ]; then
        break
    fi

    match=$(echo "$tags" | grep -E "^${STREAM}-[0-9]{12}$" | sort | tail -1 || true)
    if [ -n "$match" ] && [[ "$match" > "$newest" ]]; then
        newest="$match"
    fi

    count=$(echo "$tags" | wc -l | tr -d ' ')
    [ "$count" -lt 1000 ] && break
    last=$(echo "$tags" | tail -1)
done

if [ -z "$newest" ]; then
    echo "ERROR: no date-stamped tags found for ${ORG}/${REPO} stream '${STREAM}'." >&2
    echo "       Check the stream name; e.g. python-fips uses '3.11' and '3.11-dev'." >&2
    exit 1
fi

DIGEST=$(curl -sf -D - -o /dev/null -X GET \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Accept: application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json" \
    "https://cgr.dev/v2/${ORG}/${REPO}/manifests/${newest}" \
    | grep -i '^docker-content-digest' | tr -d '\r' | awk '{print $2}')

if [ -z "$DIGEST" ]; then
    echo "ERROR: resolved tag ${newest} but could not read its digest." >&2
    exit 1
fi

echo "cgr.dev/${ORG}/${REPO}:${newest}@${DIGEST}"
