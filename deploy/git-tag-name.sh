#!/bin/bash
# Returns a string to be used as a docker tag revision.
# If it's in a clean git repo, it returns the commit's short hash with branch name like ce37fd7-main
# If the working tree is dirty, it returns something like main-ce37fd7-dirty-e52e78f86e575bd
#     including the branch name, and a consistent hash of the uncommitted changes

set -e

fail() {
    echo $1
    exit 1
}

if [[ ! -z "${OVERRIDE_GIT_TAG_NAME}" ]]; then
    echo $OVERRIDE_GIT_TAG_NAME
    exit 0
fi

# Figure out which SHA utility exists on this machine.
HASH_FUNC=sha1sum
which $HASH_FUNC > /dev/null || HASH_FUNC=shasum
which $HASH_FUNC > /dev/null || fail "Can't find SHA utility"

# Try to get current branch out of GITHUB_REF for CI
# The ##*/ deletes everything up to /
CURRENT_BRANCH=${GITHUB_REF##*/}
# Now generate the short commit
CURRENT_COMMIT=$(echo $GITHUB_SHA | cut -c -9)

# If we're not running in CI, GITHUB_REF and GITHUB_SHA won't be set.
# In this case, figure them out from our git repository
# (If we do this during github CI, we get a useless unique commit on the "merge" branch.)
# When infering CURRENT_BRANCH, convert '/'s to '-'s, since '/' is not allowed in docker tags but
# is part of common git branch naming formats e.g. "feature/branch-name" or "user/branch-name"
CURRENT_BRANCH=${CURRENT_BRANCH:-$(git rev-parse --abbrev-ref HEAD | sed -e 's/\//-/g')}
CURRENT_COMMIT=${CURRENT_COMMIT:-$(git rev-parse --short=9 HEAD)}

if [[ -z "$(git status --porcelain)" ]] || [[ "${CI}" = true ]]; then
    # Working tree is clean
    echo "${CURRENT_COMMIT}-${CURRENT_BRANCH}"
else
    # Working tree is dirty.
    HASH=$(echo $(git diff && git status) | ${HASH_FUNC} | cut -c -15)
    echo "${CURRENT_BRANCH}-${CURRENT_COMMIT}-dirty-${HASH}"
fi
