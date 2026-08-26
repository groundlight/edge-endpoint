#!/bin/bash
# Start each FIPS image role briefly and assert it does not immediately crash.
#
# Usage:
#   ./smoke-test-fips-image.sh <image-ref> [platform]
#
# WHY THIS EXISTS
#
# verify-fips-image.sh proves FIPS-enforcing and no shell. It does not prove the
# app runs. Distroless + uid 65532 + pre-chowned paths fail at start, not at
# build. Same verify/smoke split as gep and zuuul.
#
# This is not a full integration test. Edge-endpoint is eight Helm roles in one
# image, so this execs those entrypoints (imports, cert gen, sqlite init,
# nginx -t). It does not boot uvicorn: startup calls cloud me() and needs a
# device token, which CI does not have. Live-server coverage is k3s. mount-s3
# FUSE against a real bucket is a local privileged Docker spike, not CI.

set -euo pipefail

IMAGE="${1:-}"
PLATFORM="${2:-}"

if [ -z "$IMAGE" ]; then
    echo "Usage: $0 <image-ref> [platform]" >&2
    exit 1
fi

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

echo "Smoke testing edge-endpoint FIPS roles (${IMAGE}${PLATFORM:+, $PLATFORM})"

if dr --user 65532 -e CERT_DIR=/tmp/certs --entrypoint python "$IMAGE" -m app.runtime.generate_tls_cert; then
    pass "generate-tls-cert"
else
    fail "generate-tls-cert"
fi

if dr --user 65532 -e SQLITE_DIR=/tmp/sqlite --entrypoint python "$IMAGE" -m app.runtime.setup_db; then
    pass "database-prep"
else
    fail "database-prep"
fi

if dr --entrypoint python "$IMAGE" -c 'from app.runtime.mount_s3 import mount_s3_argv, drain_stale_mounts; print(mount_s3_argv("b","/m","us-west-2","/c"))'; then
    pass "mount-s3 launcher imports"
else
    fail "mount-s3 launcher imports"
fi

if dr --entrypoint python "$IMAGE" -c 'from app.runtime.check_s3_mount import is_mount_point; assert is_mount_point("/")'; then
    pass "check_s3_mount"
else
    fail "check_s3_mount"
fi

NGINX_TMP=$(mktemp)
# Bind-mounted into the container as uid 65532; mktemp is 0600 by default.
chmod 644 "$NGINX_TMP"
trap 'rm -f "$NGINX_TMP"' EXIT
cat > "$NGINX_TMP" <<'EOF'
events { worker_connections 64; }
pid /tmp/nginx.pid;
error_log /dev/stderr;
http { server { listen 127.0.0.1:18080; return 200; } }
EOF
if dr --user 65532 -v "$NGINX_TMP:/opt/nginx/nginx.conf:ro" --entrypoint python "$IMAGE" -c '
from pathlib import Path
import subprocess, sys
from app.runtime.launch_nginx import NGINX_CONF, nameserver_from_resolv_conf, write_nginx_conf
ns = nameserver_from_resolv_conf(Path("/etc/resolv.conf").read_text())
write_nginx_conf(Path("/opt/nginx/nginx.conf").read_text(), ns, NGINX_CONF)
sys.exit(subprocess.call(["nginx", "-t", "-c", str(NGINX_CONF)]))
'; then
    pass "launch_nginx renders conf; nginx -t"
else
    fail "launch_nginx renders conf; nginx -t"
fi

if dr --entrypoint python "$IMAGE" -c 'from app.main import app; print(app.title)'; then
    pass "edge-endpoint import"
else
    fail "edge-endpoint import"
fi

if dr --entrypoint python "$IMAGE" -c 'from app.status_monitor.status_web import app; print("status-monitor")'; then
    pass "status-monitor import"
else
    fail "status-monitor import"
fi

if dr --entrypoint python "$IMAGE" -c 'import app.escalation_queue.manage_reader; print("escalation-queue-reader")'; then
    pass "escalation-queue-reader import"
else
    fail "escalation-queue-reader import"
fi

if dr --entrypoint python "$IMAGE" -c 'import app.model_updater.update_models; print("inference-model-updater")'; then
    pass "inference-model-updater import"
else
    fail "inference-model-updater import"
fi

echo
if [ "$failures" -ne 0 ]; then
    echo "Smoke test FAILED: ${failures} problem(s)." >&2
    exit 1
fi
echo "Smoke test passed for ${IMAGE}."
