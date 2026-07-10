import io
import json
import urllib.error

import pytest

from lustre_reporter.sources import atlassian
from lustre_reporter.sources.atlassian import AtlassianError

OK = {"instances": {"cloud": {"server": "https://s/", "auth": {"email": "e", "token": "t"}}}}


def _creds(tmp_path, data):
    (tmp_path / ".jira-tool.json").write_text(json.dumps(data))
    return tmp_path


def test_cloud_creds_ok(monkeypatch, tmp_path):
    _creds(tmp_path, OK)
    monkeypatch.setattr(atlassian.Path, "home", lambda: tmp_path)
    assert atlassian.cloud_creds() == ("https://s", "e", "t")


def test_cloud_creds_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(atlassian.Path, "home", lambda: tmp_path)
    with pytest.raises(AtlassianError):
        atlassian.cloud_creds()


def test_cloud_creds_no_cloud(monkeypatch, tmp_path):
    _creds(tmp_path, {"instances": {}})
    monkeypatch.setattr(atlassian.Path, "home", lambda: tmp_path)
    with pytest.raises(AtlassianError):
        atlassian.cloud_creds()


def test_cloud_creds_missing_fields(monkeypatch, tmp_path):
    _creds(tmp_path, {"instances": {"cloud": {"auth": {"email": "e"}}}})
    monkeypatch.setattr(atlassian.Path, "home", lambda: tmp_path)
    with pytest.raises(AtlassianError):
        atlassian.cloud_creds()


def test_auth_header(monkeypatch):
    monkeypatch.setattr(atlassian, "cloud_creds", lambda: ("https://s", "e", "t"))
    assert atlassian.auth_header().startswith("Basic ")


class _Resp:
    def __init__(self, body):
        self._b = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._b


def test_cloud_get_ok(monkeypatch):
    monkeypatch.setattr(atlassian, "cloud_creds", lambda: ("https://s", "e", "t"))
    monkeypatch.setattr(atlassian.urllib.request, "urlopen", lambda req, timeout=45: _Resp(b'[{"x":1}]'))
    assert atlassian.cloud_get("/p") == [{"x": 1}]


def test_cloud_get_empty(monkeypatch):
    monkeypatch.setattr(atlassian, "cloud_creds", lambda: ("https://s", "e", "t"))
    monkeypatch.setattr(atlassian.urllib.request, "urlopen", lambda req, timeout=45: _Resp(b""))
    assert atlassian.cloud_get("/p") is None


def test_cloud_get_http_error(monkeypatch):
    monkeypatch.setattr(atlassian, "cloud_creds", lambda: ("https://s", "e", "t"))

    def boom(req, timeout=45):
        raise urllib.error.HTTPError("u", 404, "nf", {}, io.BytesIO(b"no"))
    monkeypatch.setattr(atlassian.urllib.request, "urlopen", boom)
    with pytest.raises(AtlassianError, match="404"):
        atlassian.cloud_get("/p")


def test_cloud_get_other_error(monkeypatch):
    monkeypatch.setattr(atlassian, "cloud_creds", lambda: ("https://s", "e", "t"))

    def boom(req, timeout=45):
        raise ValueError("x")
    monkeypatch.setattr(atlassian.urllib.request, "urlopen", boom)
    with pytest.raises(AtlassianError):
        atlassian.cloud_get("/p")
