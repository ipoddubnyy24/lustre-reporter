import contextlib
import http.client
import threading

from lustre_reporter import server
from lustre_reporter.cli import ToolResult


def okt(data):
    return ToolResult(ok=True, data=data)


# ---------------- small helpers ----------------
def test_int_helper():
    assert server._int({"d": ["5"]}, "d", 1) == 5
    assert server._int({"d": ["x"]}, "d", 1) == 1
    assert server._int({}, "d", 7) == 7


def test_attach_ticket_urls(cfg):
    tks = [{"key": "LU-1", "project": "LU"}, {"key": "EX-2", "project": "EX"}]
    server._attach_ticket_urls(cfg, tks)
    assert tks[0]["url"].endswith("/LU-1") and tks[0]["is_cloud"] is False
    assert "ime-ddn" in tks[1]["url"] and tks[1]["is_cloud"] is True


def test_ttlcache(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(server.time, "time", lambda: clock[0])
    c = server.TTLCache(ttl=10)
    assert c.get("k") is None
    c.set("k", "v")
    assert c.get("k") == "v"
    clock[0] = 105
    assert c.get("k") == "v"
    clock[0] = 111
    assert c.get("k") is None            # expired
    c.set("j", "w")
    c.drop("j")
    assert c.get("j") is None


# ---------------- endpoint functions ----------------
def test_api_config(cfg):
    c = server.api_config(cfg, {})
    assert [b["key"] for b in c["branches"]] == ["es6", "es7"]
    assert c["confluence_enabled"] is True and "today" in c
    assert c["defaults"]["landed_days"] == 7


def test_api_stability_ok(monkeypatch, cfg):
    monkeypatch.setattr(server.maloo, "sessions",
                        lambda job, days=14, limit=500: okt([{"submission": "2026-07-03T00:00:00Z",
                                                              "passed": 1, "failed": 0, "aborted": 0, "total": 1}]))
    r = server.api_stability(cfg, {"branch": ["es6"], "days": ["30"]})
    assert r["ok"] and r["summary"]["sessions"] == 1 and r["trigger_job"] == "lustre-b_es6_0"


def test_api_stability_from_to_filter(monkeypatch, cfg):
    data = [{"submission": "2026-07-03", "passed": 1, "failed": 0, "aborted": 0, "total": 1},
            {"submission": "2026-08-01", "passed": 1, "failed": 0, "aborted": 0, "total": 1}]
    monkeypatch.setattr(server.maloo, "sessions", lambda job, days=14, limit=500: okt(data))
    r = server.api_stability(cfg, {"branch": ["es6"], "from": ["2026-07-01"], "to": ["2026-07-31"]})
    assert r["ok"] and r["summary"]["sessions"] == 1     # Aug session filtered out


def test_api_stability_bad_from(monkeypatch, cfg):
    monkeypatch.setattr(server.maloo, "sessions", lambda job, days=14, limit=500: okt([]))
    r = server.api_stability(cfg, {"branch": ["es6"], "from": ["notadate"], "days": ["5"]})
    assert r["ok"] and r["days"] == 5


def test_api_stability_auth(monkeypatch, cfg):
    monkeypatch.setattr(server.maloo, "sessions",
                        lambda job, days=14, limit=500: ToolResult(ok=False, data=None, error="401", kind="auth"))
    r = server.api_stability(cfg, {"branch": ["es6"]})
    assert r["ok"] is False and r["kind"] == "auth"


def test_api_top_failures(monkeypatch, cfg):
    monkeypatch.setattr(server.maloo, "top_failures",
                        lambda job, days=30, sessions=60, limit=25: okt([{"rank": 1}]))
    assert server.api_top_failures(cfg, {"branch": ["es6"]})["failures"] == [{"rank": 1}]
    monkeypatch.setattr(server.maloo, "top_failures",
                        lambda job, **k: ToolResult(ok=False, data=None, error="e", kind="auth"))
    assert server.api_top_failures(cfg, {"branch": ["es6"]})["ok"] is False


def test_api_landed_days(monkeypatch, cfg):
    monkeypatch.setattr(server.gerrit, "merged_last_days",
                        lambda p, b, d, limit=300: okt([{"number": 1, "tickets": [{"key": "LU-1", "project": "LU"}]}]))
    r = server.api_landed(cfg, {"days": ["7"]})
    assert r["mode"] == "days"
    assert r["branches"][0]["patches"][0]["tickets"][0]["url"].endswith("/LU-1")


def test_api_landed_days_error(monkeypatch, cfg):
    monkeypatch.setattr(server.gerrit, "merged_last_days",
                        lambda p, b, d, limit=300: ToolResult(ok=False, data=None, error="e", kind="auth"))
    assert server.api_landed(cfg, {"days": ["7"]})["branches"][0]["ok"] is False


def test_api_landed_tag_ok(monkeypatch, cfg):
    monkeypatch.setattr(server.git_tags, "last_tag",
                        lambda clone, br, tag=None, fetch_cfg=None: {"ok": True, "tag": "T",
                                                                     "date": "2026-07-01", "manual": bool(tag)})
    monkeypatch.setattr(server.gerrit, "merged_since",
                        lambda p, b, since, limit=500: okt([{"number": 2, "tickets": []}]))
    b0 = server.api_landed(cfg, {"mode": ["tag"]})["branches"][0]
    assert b0["ok"] and b0["tag"] == "T" and b0["tag_manual"] is False and b0["count"] == 1


def test_api_landed_tag_manual_note(monkeypatch, cfg):
    monkeypatch.setattr(server.git_tags, "last_tag",
                        lambda clone, br, tag=None, fetch_cfg=None: {"ok": True, "tag": tag, "date": "d",
                                                                     "manual": True, "fetch_note": "⚠ stale"})
    monkeypatch.setattr(server.gerrit, "merged_since", lambda p, b, since, limit=500: okt([]))
    r = server.api_landed(cfg, {"mode": ["tag"], "tag": ["X"]})
    assert r["tag"] == "X" and r["branches"][0]["tag_manual"] is True
    assert r["branches"][0]["fetch_note"] == "⚠ stale"


def test_api_landed_tag_error(monkeypatch, cfg):
    monkeypatch.setattr(server.git_tags, "last_tag",
                        lambda clone, br, tag=None, fetch_cfg=None: {"ok": False, "error": "no ref", "fetch_note": "⚠ x"})
    b0 = server.api_landed(cfg, {"mode": ["tag"]})["branches"][0]
    assert b0["ok"] is False and b0["error"] == "no ref" and b0["fetch_note"] == "⚠ x"


def test_api_backports(monkeypatch, cfg):
    monkeypatch.setattr(server.backport, "analyze",
                        lambda c, days, only_gaps=True: {
                            "candidates": [{"tickets": [{"key": "EX-1", "project": "EX"}]}],
                            "branches": [{"key": "es6"}, {"key": "es7"}]})
    r = server.api_backports(cfg, {"days": ["30"]})
    assert r["candidates"][0]["tickets"][0]["url"].endswith("/EX-1")
    assert r["branches"][0]["ping_email"] == "lixi@ddn.com"


def test_api_ticket_lu_and_cloud(monkeypatch, cfg):
    seen = {}
    monkeypatch.setattr(server.jira, "get",
                        lambda key, cloud=False: (seen.__setitem__("cloud", cloud), okt({"key": key, "summary": "s"}))[1])
    r = server.api_ticket(cfg, {"key": ["LU-1"]})
    assert r["ok"] and r["is_cloud"] is False and seen["cloud"] is False and r["url"].endswith("/LU-1")
    r2 = server.api_ticket(cfg, {"key": ["EX-9"]})
    assert r2["is_cloud"] is True and "ime-ddn" in r2["url"]


def test_api_ticket_bad_key(cfg):
    assert server.api_ticket(cfg, {"key": ["nope"]})["ok"] is False


def test_api_ticket_error(monkeypatch, cfg):
    monkeypatch.setattr(server.jira, "get",
                        lambda key, cloud=False: ToolResult(ok=False, data=None, error="e", kind="auth"))
    r = server.api_ticket(cfg, {"key": ["LU-1"]})
    assert r["ok"] is False and r["url"].endswith("/LU-1")


def test_api_change(monkeypatch, cfg):
    assert server.api_change(cfg, {})["ok"] is False
    monkeypatch.setattr(server.gerrit, "change_info",
                        lambda url: okt({"reviewers": [{"approvals": {"Verified": "+1"}}], "jenkins_build": "J"}))
    assert server.api_change(cfg, {"url": ["http://c/1"]})["label"] == "V+1"
    monkeypatch.setattr(server.gerrit, "change_info",
                        lambda url: ToolResult(ok=False, data=None, error="e", kind="error"))
    assert server.api_change(cfg, {"url": ["u"]})["ok"] is False


def test_api_ping(cfg):
    r = server.api_ping(cfg, {"branch": ["es6"], "subject": ["LU-1 x"], "url": ["http://p/1"], "ticket": ["LU-1"]})
    assert r["ok"] and r["email"] == "lixi@ddn.com" and "b_es6_0" in r["message"]
    assert server.api_ping(cfg, {"branch": ["nope"]})["ok"] is False


def test_api_publish(monkeypatch, cfg):
    monkeypatch.setattr(server.publish, "publish_all", lambda c: {"ok": True, "results": []})
    assert server.api_publish(cfg, {}) == {"ok": True, "results": []}


def test_api_slack_report(monkeypatch, cfg):
    monkeypatch.setattr(server.daily_report, "send_daily", lambda c: {"ok": True, "date": "d"})
    assert server.api_slack_report(cfg, {}) == {"ok": True, "date": "d"}


# ---------------- live HTTP integration (Handler / routing / cache / static) ----------------
@contextlib.contextmanager
def _running(cfg):
    cfg.host, cfg.port = "127.0.0.1", 0
    httpd = server.make_server(cfg, cache_ttl=300)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield port
    finally:
        httpd.shutdown()


def _get(port, path):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, body


def test_http_integration(monkeypatch, cfg):
    monkeypatch.setattr(server.gerrit, "merged_last_days",
                        lambda p, b, d, limit=300: okt([{"number": 1, "tickets": []}]))
    with _running(cfg) as port:
        assert _get(port, "/api/config")[0] == 200
        s, body = _get(port, "/")
        assert s == 200 and b"EXA Reporter" in body
        assert _get(port, "/index.html")[0] == 200
        assert _get(port, "/static/style.css")[0] == 200
        assert _get(port, "/static/app.js")[0] == 200
        assert _get(port, "/static/")[0] == 200   # empty rel -> index.html
        # cached endpoint: miss, hit, refresh
        assert _get(port, "/api/landed?days=7")[0] == 200
        assert _get(port, "/api/landed?days=7")[0] == 200
        assert _get(port, "/api/landed?days=7&refresh=1")[0] == 200
        # 404s
        assert _get(port, "/nope")[0] == 404
        assert _get(port, "/static/missing.css")[0] == 404
        # traversal guard (raw ".." — http.client does not normalize)
        assert _get(port, "/static/../pyproject.toml")[0] == 404


def test_http_500(monkeypatch, cfg):
    def boom(c, days, only_gaps=True):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(server.backport, "analyze", boom)
    with _running(cfg) as port:
        assert _get(port, "/api/backports")[0] == 500
