"""Regression tests for the pinned self-signed TLS cert generator.

These guard the two behaviors the pinning fix depends on: an existing valid
cert survives repeated generator runs (so it stays stable across pod restarts),
and a broken cert/key pair is self-healed rather than served as-is.
"""

from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.runtime.generate_tls_cert import main as generate_tls_cert


def _run_generator(cert_dir: Path, monkeypatch) -> None:
    """Invoke the generator with its cert directory pointed at cert_dir."""
    monkeypatch.setenv("CERT_DIR", str(cert_dir))
    assert generate_tls_cert() == 0


def _fingerprint(cert_file: Path) -> bytes:
    """Return the SHA-256 digest of the certificate DER."""
    cert = x509.load_pem_x509_certificate(cert_file.read_bytes())
    return cert.fingerprint(hashes.SHA256())


def _keys_match(cert_file: Path, key_file: Path) -> bool:
    """Return whether the private key corresponds to the certificate."""
    cert = x509.load_pem_x509_certificate(cert_file.read_bytes())
    key = serialization.load_pem_private_key(key_file.read_bytes(), password=None)
    return cert.public_key().public_numbers() == key.public_key().public_numbers()


def test_valid_cert_is_pinned_across_runs(tmp_path: Path, monkeypatch):
    _run_generator(tmp_path, monkeypatch)
    cert_file = tmp_path / "certificate.crt"
    key_file = tmp_path / "private.key"
    assert cert_file.exists() and key_file.exists()
    assert key_file.stat().st_mode & 0o777 == 0o600
    assert _keys_match(cert_file, key_file)
    first = _fingerprint(cert_file)

    _run_generator(tmp_path, monkeypatch)
    second = _fingerprint(cert_file)
    assert first == second, "a valid pinned cert must survive a second generator run"


def test_mismatched_key_is_replaced(tmp_path: Path, monkeypatch):
    _run_generator(tmp_path, monkeypatch)
    cert_file = tmp_path / "certificate.crt"
    key_file = tmp_path / "private.key"
    original = _fingerprint(cert_file)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_file.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    assert not _keys_match(cert_file, key_file)

    _run_generator(tmp_path, monkeypatch)
    assert _keys_match(cert_file, key_file), "a mismatched cert/key pair must be regenerated"
    assert _fingerprint(cert_file) != original
