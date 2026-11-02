"""Tests that both nginx configs verify the cloud upstream's TLS certificate."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY_DIRECTIVES = (
    "proxy_ssl_verify on;",
    "proxy_ssl_trusted_certificate /etc/ssl/certs/ca-certificates.crt;",
    "proxy_ssl_verify_depth 3;",
)


@pytest.mark.parametrize("conf", ["configs/nginx.conf", "deploy/helm/groundlight-edge-endpoint/files/nginx.conf"])
def test_fallback_verifies_upstream_tls(conf: str):
    fallback = (REPO_ROOT / conf).read_text().split("location @fallback", 1)[1]
    fallback_lines = [line.strip() for line in fallback.splitlines()]
    for directive in VERIFY_DIRECTIVES:
        assert directive in fallback_lines
