import subprocess
import threading
import webbrowser
from datetime import datetime

import pytest

import lustre_reporter.publish as pub
from lustre_reporter import __main__ as main_mod


# ---------------- ensure_cert ----------------
def test_ensure_cert_existing(tmp_path):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    cert.write_text("c")
    key.write_text("k")
    assert main_mod.ensure_cert(str(tmp_path)) == (cert, key)


def test_ensure_cert_generate(monkeypatch, tmp_path):
    monkeypatch.setattr(main_mod.shutil, "which", lambda n: "/usr/bin/openssl")
    calls = []
    monkeypatch.setattr(main_mod.subprocess, "run",
                        lambda *a, **k: calls.append(a) or
                        subprocess.CompletedProcess(a, 0, "", ""))
    cert, key = main_mod.ensure_cert(str(tmp_path / "new"))
    assert str(cert).endswith("cert.pem") and str(key).endswith("key.pem") and calls


def test_ensure_cert_no_openssl(monkeypatch, tmp_path):
    monkeypatch.setattr(main_mod.shutil, "which", lambda n: None)
    with pytest.raises(SystemExit):
        main_mod.ensure_cert(str(tmp_path / "x"))


def test_ensure_cert_openssl_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(main_mod.shutil, "which", lambda n: "/usr/bin/openssl")

    def boom(*a, **k):
        raise subprocess.CalledProcessError(1, "openssl", stderr="bad")
    monkeypatch.setattr(main_mod.subprocess, "run", boom)
    with pytest.raises(SystemExit):
        main_mod.ensure_cert(str(tmp_path / "x"))


# ---------------- scheduler ----------------
def test_scheduler_disabled(cfg):
    cfg.confluence = {"enabled": False}
    before = threading.active_count()
    assert main_mod._start_confluence_scheduler(cfg) is None
    assert threading.active_count() == before


def test_scheduler_auto_off(cfg):
    cfg.confluence = {"enabled": True, "auto_publish": False}
    before = threading.active_count()
    main_mod._start_confluence_scheduler(cfg)
    assert threading.active_count() == before


def test_scheduler_enabled_starts_thread(monkeypatch, cfg):
    # far-future next update so the daemon thread just sleeps harmlessly
    monkeypatch.setattr(pub, "now_pt", lambda: datetime(2026, 1, 1))
    monkeypatch.setattr(pub, "next_update_pt", lambda now=None: datetime(2100, 1, 1))
    main_mod._start_confluence_scheduler(cfg)
    assert any(t.name == "confluence-scheduler" for t in threading.enumerate())


# ---------------- main() ----------------
def test_main_publish_now_ok(monkeypatch):
    monkeypatch.setattr(pub, "publish_all", lambda c: {"ok": True})
    assert main_mod.main(["--publish-now"]) == 0


def test_main_publish_now_fail(monkeypatch):
    monkeypatch.setattr(pub, "publish_all", lambda c: {"ok": False, "error": "x"})
    assert main_mod.main(["--publish-now"]) == 1


class _FakeCtx:
    def load_cert_chain(self, **k):
        pass

    def wrap_socket(self, sock, server_side):
        return sock


class _FakeHttpd:
    def __init__(self):
        self.socket = object()
        self.stopped = False

    def serve_forever(self):
        raise KeyboardInterrupt

    def shutdown(self):
        self.stopped = True


def _patch_serve(monkeypatch, httpd):
    monkeypatch.setattr(main_mod, "ensure_cert", lambda d: ("c", "k"))
    monkeypatch.setattr(main_mod.ssl, "SSLContext", lambda proto: _FakeCtx())
    monkeypatch.setattr(main_mod, "make_server", lambda cfg, cache_ttl=300: httpd)
    monkeypatch.setattr(main_mod, "_start_confluence_scheduler", lambda cfg: None)


def test_main_serves_and_shuts_down(monkeypatch):
    httpd = _FakeHttpd()
    _patch_serve(monkeypatch, httpd)
    assert main_mod.main(["--host", "127.0.0.1", "--port", "0"]) == 0
    assert httpd.stopped is True


def test_main_open_browser(monkeypatch):
    httpd = _FakeHttpd()
    _patch_serve(monkeypatch, httpd)
    opened = {}
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.setdefault("u", url))
    assert main_mod.main(["--open"]) == 0
    assert opened["u"].startswith("https://")


def test_main_bind_error(monkeypatch):
    monkeypatch.setattr(main_mod, "ensure_cert", lambda d: ("c", "k"))
    monkeypatch.setattr(main_mod.ssl, "SSLContext", lambda proto: _FakeCtx())

    def boom(cfg, cache_ttl=300):
        raise OSError("addr in use")
    monkeypatch.setattr(main_mod, "make_server", boom)
    with pytest.raises(SystemExit):
        main_mod.main(["--port", "0"])


def test_ensure_cert_tempfile_fails(monkeypatch, tmp_path):
    # tempfile never created -> ensure_cert's `finally: if cnf_path` false arc
    monkeypatch.setattr(main_mod.shutil, "which", lambda n: "/usr/bin/openssl")

    def boom(*a, **k):
        raise RuntimeError("tmpfail")
    monkeypatch.setattr(main_mod.tempfile, "NamedTemporaryFile", boom)
    with pytest.raises(RuntimeError):
        main_mod.ensure_cert(str(tmp_path / "x"))
