"""Generate or reuse a pinned self-signed TLS cert for nginx HTTPS."""

import datetime
import os
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

REUSE_IF_VALID_FOR = datetime.timedelta(days=30)
VALIDITY = datetime.timedelta(days=3650)
RSA_BITS = 2048
SUBJECT = x509.Name(
    [
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Washington"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Seattle"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Groundlight"),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Engineering"),
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
    ]
)


def cert_paths() -> tuple[Path, Path, Path]:
    """Return (cert dir, cert file, key file), honoring CERT_DIR."""
    cert_dir = Path(os.environ.get("CERT_DIR", "/etc/nginx/certs"))
    return cert_dir, cert_dir / "certificate.crt", cert_dir / "private.key"


def _load_cert(path: Path) -> x509.Certificate:
    return x509.load_pem_x509_certificate(path.read_bytes())


def _load_key(path: Path):
    """Load a PEM private key from path."""
    return serialization.load_pem_private_key(path.read_bytes(), password=None)


def cert_is_reusable() -> bool:
    """Return True when both files exist, the cert lasts 30+ more days, and the key matches."""
    _cert_dir, cert_file, key_file = cert_paths()
    if not cert_file.is_file() or not key_file.is_file():
        return False
    try:
        cert = _load_cert(cert_file)
        key = _load_key(key_file)
    except Exception:
        return False
    now = datetime.datetime.now(datetime.timezone.utc)
    if cert.not_valid_after_utc - now < REUSE_IF_VALID_FOR:
        return False
    return cert.public_key().public_numbers() == key.public_key().public_numbers()


def generate_cert_and_key() -> tuple[bytes, bytes]:
    """Return a new PEM cert and matching 2048-bit RSA private key."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=RSA_BITS)
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(SUBJECT)
        .issuer_name(SUBJECT)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + VALIDITY)
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    return cert_pem, key_pem


def main() -> int:
    """Keep a reusable pinned cert, or write a new self-signed pair into CERT_DIR."""
    if cert_is_reusable():
        print("Existing TLS certificate is still valid and matches its key; keeping the pinned cert.")
        return 0

    print("Generating a new self-signed TLS certificate (cert/key missing, mismatched, or near expiry)...")
    cert_pem, key_pem = generate_cert_and_key()
    cert_dir, cert_file, key_file = cert_paths()
    cert_dir.mkdir(parents=True, exist_ok=True)
    cert_file.write_bytes(cert_pem)
    key_file.write_bytes(key_pem)
    key_file.chmod(0o600)
    print(f"TLS certificate and key copied to {cert_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
