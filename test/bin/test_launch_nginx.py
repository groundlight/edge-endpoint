"""Tests for nginx resolver templating."""

from pathlib import Path

from app.runtime.launch_nginx import nameserver_from_resolv_conf, write_nginx_conf


def test_nameserver_from_resolv_conf():
    text = "search cluster.local\nnameserver 10.43.0.10\nnameserver 8.8.8.8\n"
    assert nameserver_from_resolv_conf(text) == "10.43.0.10"


def test_write_nginx_conf(tmp_path: Path):
    dest = tmp_path / "nginx.conf"
    write_nginx_conf("resolver __NAME_SERVER__ valid=30s;", "10.43.0.10", dest)
    assert dest.read_text() == "resolver 10.43.0.10 valid=30s;"
