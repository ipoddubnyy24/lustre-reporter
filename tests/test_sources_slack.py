import io
import json
import urllib.error

from lustre_reporter.sources import slack


def test_configured():
    assert slack.configured({"enabled": True, "webhook_url": "x"})
    assert slack.configured({"enabled": True, "bot_token": "t"})
    assert not slack.configured({"enabled": False, "webhook_url": "x"})
    assert not slack.configured({"enabled": True})


def test_post_none_configured():
    assert slack.post({}, "hi")["ok"] is False


def test_post_webhook_ok(monkeypatch):
    monkeypatch.setattr(slack, "_post", lambda url, payload, headers: (200, "ok"))
    assert slack.post({"webhook_url": "http://hook"}, "hi")["ok"] is True


def test_post_webhook_bad_status(monkeypatch):
    monkeypatch.setattr(slack, "_post", lambda url, payload, headers: (500, "boom"))
    r = slack.post({"webhook_url": "http://hook"}, "hi")
    assert r["ok"] is False and "500" in r["error"]


def test_post_webhook_http_error(monkeypatch):
    def boom(url, payload, headers):
        raise urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(b"nope"))
    monkeypatch.setattr(slack, "_post", boom)
    assert slack.post({"webhook_url": "http://hook"}, "hi")["ok"] is False


def test_post_webhook_other_error(monkeypatch):
    def boom(url, payload, headers):
        raise ValueError("x")
    monkeypatch.setattr(slack, "_post", boom)
    assert slack.post({"webhook_url": "http://hook"}, "hi")["ok"] is False


def test_post_bot_ok(monkeypatch):
    monkeypatch.setattr(slack, "_post",
                        lambda url, payload, headers: (200, json.dumps({"ok": True, "ts": "1.2", "channel": "C1"})))
    r = slack.post({"bot_token": "t", "channel": "C1"}, "hi")
    assert r["ok"] is True and r["ts"] == "1.2"


def test_post_bot_slack_error(monkeypatch):
    monkeypatch.setattr(slack, "_post",
                        lambda url, payload, headers: (200, json.dumps({"ok": False, "error": "channel_not_found"})))
    r = slack.post({"bot_token": "t", "channel": "C1"}, "hi")
    assert r["ok"] is False and "channel_not_found" in r["error"]


def test_post_bot_no_channel():
    r = slack.post({"bot_token": "t"}, "hi")
    assert r["ok"] is False and "channel" in r["error"]


def test_post_bot_http_error(monkeypatch):
    def boom(url, payload, headers):
        raise urllib.error.HTTPError("u", 500, "e", {}, io.BytesIO(b""))
    monkeypatch.setattr(slack, "_post", boom)
    assert slack.post({"bot_token": "t", "channel": "C"}, "hi")["ok"] is False


def test_post_bot_other_error(monkeypatch):
    def boom(url, payload, headers):
        raise ValueError("x")
    monkeypatch.setattr(slack, "_post", boom)
    assert slack.post({"bot_token": "t", "channel": "C"}, "hi")["ok"] is False


def test_underlying_post_calls_urlopen(monkeypatch):
    class R:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"ok"
    monkeypatch.setattr(slack.urllib.request, "urlopen", lambda req, timeout=30: R())
    assert slack._post("http://x", {"a": 1}, {}) == (200, "ok")
