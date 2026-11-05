"""Fail the image build if a CA bundle still trusts a distrusted root.

Usage:
    python deploy/bin/check_distrusted_roots.py [extra-bundle ...]

Checks the system bundle, certifi's bundle, OpenSSL's default CA file and CA directory (what
Python's default ssl context loads), plus any extra PEM bundles given as arguments. Exits
non-zero if a bundle is missing or empty, or if any checked file contains a distrusted root.
"""

import hashlib
import os
import re
import ssl
import sys
from pathlib import Path

import certifi

# SHA-256 of each root's DER encoding. Both anchor chains to the eMudhra intermediates whose
# private keys were published.
DISTRUSTED_ROOTS = {
    "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b": "emSign ECC Root CA - G3",
    "d7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4": "Comodo AAA Services root",
}

SYSTEM_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"
PEM_CERT = re.compile(r"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----", re.S)


def fingerprints(path: Path) -> set[str]:
    """Return the SHA-256 fingerprint of every PEM certificate in a file."""
    pems = PEM_CERT.findall(path.read_text(errors="ignore"))
    return {hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest() for pem in pems}


def distrusted_in(fps: set[str]) -> list[str]:
    return [name for fp, name in DISTRUSTED_ROOTS.items() if fp in fps]


def check_bundle(bundle: str) -> list[str]:
    """Return the problems found in one PEM bundle (empty when it is clean)."""
    path = Path(bundle)
    if not path.is_file():
        return ["bundle not found"]
    fps = fingerprints(path)
    if not fps:
        return ["no certificates in bundle"]
    return [f"trusts {name}" for name in distrusted_in(fps)]


def check_directory(directory: str) -> list[str]:
    """Return the problems found across every file in an OpenSSL CA directory."""
    problems = []
    for entry in sorted(Path(directory).iterdir()):
        if entry.is_file():
            problems += [f"{entry.name} trusts {name}" for name in distrusted_in(fingerprints(entry))]
    return problems


def main(extra_bundles: list[str]) -> int:
    defaults = ssl.get_default_verify_paths()
    bundles = [SYSTEM_BUNDLE, certifi.where(), *extra_bundles]
    if defaults.cafile and Path(defaults.cafile).is_file():
        bundles.append(defaults.cafile)

    results = {}
    seen = set()
    for bundle in bundles:
        real = os.path.realpath(bundle)
        if real not in seen:
            seen.add(real)
            results[bundle] = check_bundle(bundle)
    if defaults.capath and Path(defaults.capath).is_dir():
        results[f"{defaults.capath}/"] = check_directory(defaults.capath)

    for name, problems in results.items():
        print(f"{name}: {'; '.join(problems) if problems else 'ok'}")
    return 1 if any(results.values()) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
