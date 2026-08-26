"""Template nginx.conf with the cluster DNS resolver IP, then exec nginx as PID 1."""

import os
import sys
from pathlib import Path

from app.runtime.generate_tls_cert import main as generate_tls_cert

NGINX_TEMPLATE = Path("/opt/nginx/nginx.conf")
NGINX_CONF = Path("/etc/nginx/nginx.conf")


def nameserver_from_resolv_conf(text: str) -> str:
    """Return the first nameserver address from a resolv.conf body."""
    for line in text.splitlines():
        if line.startswith("nameserver "):
            return line.split()[1]
    raise RuntimeError("no nameserver found in /etc/resolv.conf")


def write_nginx_conf(template: str, nameserver: str, dest: Path) -> None:
    """Replace the resolver placeholder and write nginx.conf."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(template.replace("__NAME_SERVER__", nameserver))


def main() -> int:
    """Render nginx.conf, ensure a TLS cert exists, then exec nginx in the foreground."""
    nameserver = nameserver_from_resolv_conf(Path("/etc/resolv.conf").read_text())
    print(f"Using nameserver: {nameserver}")
    write_nginx_conf(NGINX_TEMPLATE.read_text(), nameserver, NGINX_CONF)

    # Always run this: it keeps a valid pinned pair and replaces expired or mismatched files.
    generate_tls_cert()

    os.execvp("nginx", ["nginx", "-g", "daemon off;"])
    return 1


if __name__ == "__main__":
    sys.exit(main())
