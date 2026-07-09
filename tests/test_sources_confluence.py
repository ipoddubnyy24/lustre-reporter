import io
import json
import urllib.error

import pytest

from lustre_reporter.sources import confluence
from lustre_reporter.sources.confluence import Confluence, ConfluenceError


def _creds(tmp_path, data):
    (tmp_path / ".jira-tool.json").write_text(json.dumps(data))
    return tmp_path


def test_load_creds_ok(monkeypatch, tmp_path):
    _creds(tmp_path, {"instances": {"cloud": {"server": "https://s/",
                                              "auth": {"email": "e", "token": "t"}}}})
    monkeypatch.setattr(confluence.Path, "home", lambda: tmp_path)
    assert confluence._load_cloud_creds() == ("https://s", "e", "t")


def test_load_creds_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(confluence.Path, "home", lambda: tmp_path)
    with pytest.raises(ConfluenceError):
        confluence._load_cloud_creds()


def test_load_creds_no_cloud(monkeypatch, tmp_path):
    _creds(tmp_path, {"instances": {}})
    monkeypatch.setattr(confluence.Path, "home", lambda: tmp_path)
    with pytest.raises(ConfluenceError):
        confluence._load_cloud_creds()


def test_load_creds_missing_fields(monkeypatch, tmp_path):
    _creds(tmp_path, {"instances": {"cloud": {"auth": {"email": "e"}}}})
    monkeypatch.setattr(confluence.Path, "home", lambda: tmp_path)
    with pytest.raises(ConfluenceError):
        confluence._load_cloud_creds()


def _client(monkeypatch):
    monkeypatch.setattr(confluence, "_load_cloud_creds", lambda: ("https://s", "e", "t"))
    return Confluence()


def test_init_base(monkeypatch):
    assert _client(monkeypatch).base == "https://s/wiki"


def test_init_site_override(monkeypatch):
    monkeypatch.setattr(confluence, "_load_cloud_creds", lambda: ("https://s", "e", "t"))
    assert Confluence("https://other/").base == "https://other/wiki"


def test_find_page(monkeypatch):
    c = _client(monkeypatch)
    monkeypatch.setattr(c, "_req", lambda m, p, body=None: {"results": [{"id": "1"}]})
    assert c.find_page("SP", "T") == {"id": "1"}
    monkeypatch.setattr(c, "_req", lambda m, p, body=None: {"results": []})
    assert c.find_page("SP", "T") is None


def test_upsert_create(monkeypatch):
    c = _client(monkeypatch)
    calls = []

    def req(method, path, body=None):
        calls.append((method, path))
        if method == "GET":
            return {"results": []}
        return {"id": "9", "_links": {"webui": "/p/9"}}
    monkeypatch.setattr(c, "_req", req)
    r = c.upsert("SP", "PA", "T", "<p/>")
    assert r == {"action": "created", "id": "9", "url": "https://s/wiki/p/9"}
    assert ("POST", "/api/v2/pages") in calls


def test_upsert_update_increments_version(monkeypatch):
    c = _client(monkeypatch)

    def req(method, path, body=None):
        if method == "GET" and "?" in path:
            return {"results": [{"id": "5"}]}
        if method == "GET":
            return {"version": {"number": 3}}
        assert body["version"]["number"] == 4
        return {"id": "5", "_links": {"webui": "/p/5"}}
    monkeypatch.setattr(c, "_req", req)
    r = c.upsert("SP", None, "T", "<p/>")
    assert r["action"] == "updated" and r["url"] == "https://s/wiki/p/5"


def test_upsert_create_no_webui(monkeypatch):
    c = _client(monkeypatch)
    monkeypatch.setattr(c, "_req",
                        lambda m, p, body=None: {"results": []} if m == "GET" else {"id": "7"})
    assert c.upsert("SP", None, "T", "<p/>")["url"] is None


class _FakeResp:
    def __init__(self, body):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body


def test_req_success(monkeypatch):
    c = _client(monkeypatch)
    monkeypatch.setattr(confluence.urllib.request, "urlopen",
                        lambda req, timeout=45: _FakeResp(b'{"ok": 1}'))
    assert c._req("GET", "/x") == {"ok": 1}


def test_req_empty_body(monkeypatch):
    c = _client(monkeypatch)
    monkeypatch.setattr(confluence.urllib.request, "urlopen",
                        lambda req, timeout=45: _FakeResp(b""))
    assert c._req("POST", "/x", {"a": 1}) == {}


def test_req_http_error(monkeypatch):
    c = _client(monkeypatch)

    def boom(req, timeout=45):
        raise urllib.error.HTTPError("u", 403, "Forbidden", {}, io.BytesIO(b"nope"))
    monkeypatch.setattr(confluence.urllib.request, "urlopen", boom)
    with pytest.raises(ConfluenceError, match="403"):
        c._req("GET", "/x")


def test_req_other_error(monkeypatch):
    c = _client(monkeypatch)

    def boom(req, timeout=45):
        raise ValueError("x")
    monkeypatch.setattr(confluence.urllib.request, "urlopen", boom)
    with pytest.raises(ConfluenceError):
        c._req("GET", "/x")
