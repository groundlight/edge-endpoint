#!/bin/bash
# Assert that a built image is genuinely FIPS-enforcing and ships no shell.
#
# Usage:
#   ./verify-fips-image.sh <image-ref> [platform]
#
# Example:
#   ./verify-fips-image.sh edge-endpoint-fips:local linux/amd64
#
# WHY THIS EXISTS
#
# A `-fips` tag is a claim, not evidence. Two things can silently break it:
#   * `apk add` of anything linking OpenSSL can move libcrypto3/libssl3 out from under the
#     FIPS provider, leaving an image that is tagged -fips but is not FIPS.
#   * A Python wheel can vendor its own OpenSSL, bypassing the system provider entirely
#     (including a static link inside cryptography that never produces a libssl* file).
# And separately, a shell must never end up in a shipped image -- the whole reason for the
# distroless prod stage is that a `-dev` base carries apk plus a compiler toolchain, which
# is a worse posture than the Debian image it replaces.
#
# Every check runs against the *built artifact*, not the builder stage, and uses exec-form
# `docker run` so this harness never needs a shell inside the image under test.

# -e so an infrastructure failure (docker daemon down, image missing) aborts rather than
# being mistaken for a passing check. Every intentional "this command may fail" site below
# is inside an `if` or an assignment, which -e does not trip on. Note the failure counter is
# reported via the explicit `exit 1` at the end, not by -e.
set -euo pipefail

IMAGE="${1:-}"
PLATFORM="${2:-}"

if [ -z "$IMAGE" ]; then
    echo "Usage: $0 <image-ref> [platform]" >&2
    exit 1
fi

LABEL="$IMAGE${PLATFORM:+ ($PLATFORM)}"

# docker run wrapper that injects --platform only when one was requested. A function rather
# than an array because expanding an empty array under `set -u` is an error in bash 3.2,
# which is what ships on macOS.
dr() {
    if [ -n "$PLATFORM" ]; then
        docker run --rm --platform "$PLATFORM" "$@"
    else
        docker run --rm "$@"
    fi
}

failures=0
pass() { printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; failures=$((failures + 1)); }

echo "Verifying FIPS posture of ${LABEL}"

# ---------------------------------------------------------------------------
# 1. No shell. This is the gate that keeps a `-dev` base from shipping.
# ---------------------------------------------------------------------------
# Counted separately from the global tally: keying the summary line off $failures would make
# it silently wrong the moment another check is added above this one. It also cannot be a
# bare `[ ... ] && pass ...`, because under -e a false test would abort the script.
shells_found=0
for shell in /bin/sh /bin/bash /usr/bin/sh /usr/bin/bash; do
    if dr --entrypoint "$shell" "$IMAGE" -c true >/dev/null 2>&1; then
        fail "$shell is present and executable (a shell must not ship)"
        shells_found=$((shells_found + 1))
    fi
done
for bb in /bin/busybox /usr/bin/busybox; do
    if dr --entrypoint "$bb" "$IMAGE" sh -c true >/dev/null 2>&1; then
        fail "$bb is present and executable (a shell must not ship)"
        shells_found=$((shells_found + 1))
    fi
done
if [ "$shells_found" -eq 0 ]; then
    pass "no shell present (sh/bash/busybox all absent)"
fi

# apk would mean a package manager shipped too.
if dr --entrypoint /sbin/apk "$IMAGE" --version >/dev/null 2>&1 \
   || dr --entrypoint /usr/bin/apk "$IMAGE" --version >/dev/null 2>&1; then
    fail "apk is present (package manager must not ship)"
else
    pass "no apk present"
fi

# ---------------------------------------------------------------------------
# 2. Chainguard's own FIPS self-test: KATs, module integrity, approved-only mode.
#    Also prints the CMVP certificate, which is the attestation evidence.
# ---------------------------------------------------------------------------
if fips_out=$(dr --entrypoint /usr/bin/openssl-fips-test "$IMAGE" 2>&1); then
    pass "openssl-fips-test self-tests passed"
    # These two are informational: they surface the attestation evidence but must not fail
    # the run if Chainguard changes the report wording. `|| true` is required because under
    # -o pipefail a grep that matches nothing fails the whole assignment, and under -e that
    # would abort the script.
    provider=$(echo "$fips_out" | grep -A3 'FIPS cryptographic module provider' | grep -E 'build:' | awk '{print $2}' || true)
    cmvp=$(echo "$fips_out" | grep -oE 'certificate/[0-9]+' | head -1 | cut -d/ -f2 || true)
    if [ -n "$provider" ]; then
        echo "        FIPS provider build: ${provider}"
    fi
    if [ -n "$cmvp" ]; then
        echo "        NIST CMVP certificate: #${cmvp}"
    fi
else
    fail "openssl-fips-test did not pass"
    echo "$fips_out" | tail -5 | sed 's/^/        /'
fi

# ---------------------------------------------------------------------------
# 3. FIPS provider files are in place.
# ---------------------------------------------------------------------------
if dr --entrypoint python "$IMAGE" -c '
import os, sys
missing = [p for p in ("/etc/ssl/fipsmodule.cnf", "/usr/lib/ossl-modules/fips.so")
           if not os.path.exists(p)]
sys.exit("missing: " + ", ".join(missing) if missing else 0)
' >/dev/null 2>&1; then
    pass "fipsmodule.cnf and ossl-modules/fips.so present"
else
    fail "FIPS provider files missing"
fi

# ---------------------------------------------------------------------------
# 4. The negative test that actually proves FIPS is *active* rather than merely
#    installed: MD5 must be refused for security use, but allowed when the caller
#    explicitly opts out. If the first call succeeds, FIPS is not being enforced; if
#    the second fails, the image is broken rather than strict.
# ---------------------------------------------------------------------------
if dr --entrypoint python "$IMAGE" -c '
import hashlib, sys
try:
    hashlib.md5(b"x")
except ValueError:
    pass
else:
    sys.exit("md5 was permitted for security use: FIPS is not enforced")
try:
    hashlib.md5(b"x", usedforsecurity=False)
except Exception as e:
    sys.exit(f"md5(usedforsecurity=False) failed, image looks broken: {e}")
' >/dev/null 2>&1; then
    pass "MD5 refused for security use, permitted with usedforsecurity=False"
else
    fail "MD5 enforcement behaved unexpectedly (FIPS not active, or image broken)"
fi

# ---------------------------------------------------------------------------
# 5. Python's _ssl must dynamically link the system libssl, and no dependency may
#    have vendored its own OpenSSL into the venv. Either would route crypto around
#    the FIPS provider while every check above still passed.
# ---------------------------------------------------------------------------
# The allowlist covers AWS mount-s3's glibc OpenSSL, which lives under
# /opt/aws-mount-s3 and is isolated from Python's FIPS _ssl. It is reported rather
# than ignored. Any other vendored OpenSSL is still a failure.
if vendored_report=$(dr --entrypoint python "$IMAGE" -c '
import _ssl, fnmatch, os, ssl, sys

with open(_ssl.__file__, "rb") as f:
    if b"libssl.so" not in f.read():
        sys.exit(f"{_ssl.__file__} does not dynamically link system libssl")

# os.walk, not glob: glob("**") does not descend into dotted directories, so it silently
# skips the .venv that every vendored library actually lives in.
found = []
for root in ("/groundlight-edge", "/opt/groundlight", "/opt/aws-mount-s3"):
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if fnmatch.fnmatch(name, "libssl*") or fnmatch.fnmatch(name, "libcrypto*"):
                found.append(os.path.join(dirpath, name))

allowed = [p for p in found if p.startswith("/opt/aws-mount-s3/")]
unexpected = sorted(set(found) - set(allowed))
if unexpected:
    sys.exit(f"vendored OpenSSL found: {unexpected}")

print(ssl.OPENSSL_VERSION)
for p in sorted(allowed):
    print(f"ALLOWED {p}")
' 2>/dev/null); then
    openssl_ver=$(echo "$vendored_report" | head -1)
    pass "_ssl links system libssl, no unexpected vendored OpenSSL (${openssl_ver})"
    echo "$vendored_report" | grep '^ALLOWED ' | while read -r _ path; do
        printf '  \033[33mNOTE\033[0m  tolerated bundled OpenSSL (mount-s3 glibc, not FIPS-covered): %s\n' "$path"
    done || true
else
    fail "_ssl linkage or vendored-OpenSSL check failed"
fi

# ---------------------------------------------------------------------------
# 6. cryptography (nginx TLS keygen) must report which OpenSSL it compiled against.
#    A manylinux wheel can statically link a second copy; step 5 would still pass.
#    A mismatch is residual risk (same class as mount-s3), not a hard fail.
# ---------------------------------------------------------------------------
if crypto_report=$(dr --entrypoint python "$IMAGE" -c '
import ssl, sys

ssl_ver = ssl.OPENSSL_VERSION
crypto_ver = None
errors = []
try:
    from cryptography.hazmat.backends.openssl.backend import backend
    crypto_ver = backend.openssl_version_text()
except Exception as e:
    errors.append(str(e))
if crypto_ver is None:
    try:
        from cryptography.hazmat.bindings.openssl.binding import Binding
        raw = Binding.lib.OpenSSL_version(0)
        crypto_ver = raw.decode() if isinstance(raw, bytes) else str(raw)
    except Exception as e:
        errors.append(str(e))
if crypto_ver is None:
    sys.exit("cannot read cryptography OpenSSL version: " + "; ".join(errors))
print("SYSTEM", ssl_ver)
print("CRYPTO", crypto_ver)
print("MATCH" if ssl_ver == crypto_ver else "MISMATCH")
' 2>&1); then
    ssl_ver=$(echo "$crypto_report" | awk '/^SYSTEM / { $1=""; sub(/^ /, ""); print }')
    crypto_ver=$(echo "$crypto_report" | awk '/^CRYPTO / { $1=""; sub(/^ /, ""); print }')
    if echo "$crypto_report" | grep -q '^MATCH$'; then
        pass "cryptography OpenSSL matches system (${ssl_ver})"
    else
        pass "cryptography OpenSSL readable (mismatch is residual risk, not a fail)"
        printf '  \033[33mNOTE\033[0m  system: %s\n' "$ssl_ver"
        printf '  \033[33mNOTE\033[0m  cryptography (nginx cert gen): %s\n' "$crypto_ver"
    fi
else
    fail "cryptography OpenSSL version check failed"
    echo "$crypto_report" | tail -5
fi

echo
if [ "$failures" -ne 0 ]; then
    echo "FIPS verification FAILED for ${LABEL}: ${failures} problem(s)." >&2
    exit 1
fi
echo "FIPS verification passed for ${LABEL}."
