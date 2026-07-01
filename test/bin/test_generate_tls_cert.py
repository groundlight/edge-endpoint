"""Regression tests for the pinned self-signed TLS cert generator (GL-1699).

These guard the two behaviors the pinning fix depends on: an existing valid
cert survives repeated generator runs (so it stays stable across pod restarts),
and a broken cert/key pair is self-healed rather than served as-is.
"""

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "app" / "bin" / "generate-tls-cert.sh"


def _run_generator(cert_dir: Path) -> None:
    """Invoke the generator with its cert directory pointed at cert_dir."""
    subprocess.run(
        ["bash", str(SCRIPT)],
        env={**os.environ, "CERT_DIR": str(cert_dir)},
        check=True,
        capture_output=True,
    )


def _fingerprint(cert_file: Path) -> str:
    """Return the SHA-256 fingerprint of the certificate."""
    result = subprocess.run(
        ["openssl", "x509", "-in", str(cert_file), "-noout", "-fingerprint", "-sha256"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _keys_match(cert_file: Path, key_file: Path) -> bool:
    """Return whether the private key corresponds to the certificate."""
    cert_pubkey = subprocess.run(
        ["openssl", "x509", "-in", str(cert_file), "-noout", "-pubkey"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    key_pubkey = subprocess.run(
        ["openssl", "pkey", "-in", str(key_file), "-pubout"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return cert_pubkey == key_pubkey


def test_valid_cert_is_pinned_across_runs(tmp_path: Path):
    _run_generator(tmp_path)
    cert_file = tmp_path / "certificate.crt"
    key_file = tmp_path / "private.key"
    assert cert_file.exists() and key_file.exists()
    assert _keys_match(cert_file, key_file)
    first = _fingerprint(cert_file)

    _run_generator(tmp_path)
    second = _fingerprint(cert_file)
    assert first == second, "a valid pinned cert must survive a second generator run"


def test_mismatched_key_is_replaced(tmp_path: Path):
    _run_generator(tmp_path)
    cert_file = tmp_path / "certificate.crt"
    key_file = tmp_path / "private.key"
    original = _fingerprint(cert_file)

    # Overwrite the key with an unrelated one so the pair no longer matches.
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "RSA", "-out", str(key_file), "-pkeyopt", "rsa_keygen_bits:2048"],
        check=True,
        capture_output=True,
    )
    assert not _keys_match(cert_file, key_file)

    _run_generator(tmp_path)
    assert _keys_match(cert_file, key_file), "a mismatched cert/key pair must be regenerated"
    assert _fingerprint(cert_file) != original
