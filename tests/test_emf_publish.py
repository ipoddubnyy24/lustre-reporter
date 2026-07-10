from lustre_reporter import emf_publish
from lustre_reporter.config import Config
from lustre_reporter.sources.confluence import ConfluenceError


def _cfg():
    return Config()


class _FakeClient:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def upsert(self, space, parent, title, html):
        self.calls.append({"title": title, "html": html})
        if self.fail:
            raise ConfluenceError("boom")
        return {"action": "updated", "id": "1", "url": "u/" + title}


LANDED_OK = {
    "ok": True, "branch": "6.3.8", "tag": "T", "tag_date": "2026-06-25", "count": 1,
    "areas": [["misc", 1]],
    "patches": [{"number": 5, "url": "pr5", "subject": "EX-1 x: y", "owner": "A", "date": "2026-07-01",
                 "tickets": [{"key": "EX-1", "project": "EX"}]}],
}

COMING_OK = {"ok": True, "releases": [
    {"name": "ES6.3.9", "line": "main", "line_label": "Main release", "line_note": "stream",
     "release_date": "2026-09-04", "days": 56, "total": 2, "expected": 1.9, "items_ok": True,
     "tiers": {"review": {"count": 1, "expected": 0.95}, "progress": {"count": 1, "expected": 0.85},
               "todo": {"count": 0, "expected": 0}, "other": {"count": 0, "expected": 0}},
     "items": [{"key": "EX-1", "status": "In Review", "summary": "s", "assignee": "A", "url": "j/EX-1",
                "tier": "review", "probability": 0.95, "prs": [{"number": 5, "url": "pr5", "draft": False}]},
               {"key": "EX-2", "status": "In Progress", "summary": "t", "assignee": None, "url": "j/EX-2",
                "tier": "progress", "probability": 0.85, "prs": []}]},
    {"name": "GCP-26Q2", "line": "gcp", "line_label": "GCP", "line_note": "cloud",
     "release_date": "2026-06-30", "days": -10, "total": 0, "expected": 0.0, "items_ok": True,
     "tiers": {"review": {"count": 0, "expected": 0}, "progress": {"count": 0, "expected": 0},
               "todo": {"count": 0, "expected": 0}, "other": {"count": 1, "expected": 0}},
     "items": []},
]}


def test_render_landed_ok():
    html = emf_publish.build_landed_html(_cfg(), LANDED_OK)
    assert "Since T" in html and "EX-1" in html and "Companion EMF pages" in html
    assert "not</strong> a forecast" in html


def test_render_landed_unavailable():
    html = emf_publish.build_landed_html(_cfg(), {"ok": False, "error": "no releases"})
    assert "Unavailable" in html and "no releases" in html


def test_forecast_table_empty():
    assert "No open items" in emf_publish._forecast_table([])


def test_when():
    assert emf_publish._when(None) == "date TBD"
    assert emf_publish._when(-10) == "overdue by 10 days"
    assert emf_publish._when(5) == "in 5 days"


def test_render_coming_ok():
    line = {"key": "main", "label": "Main release", "note": "the stream"}
    html = emf_publish.build_coming_html(_cfg(), line, COMING_OK["releases"][:1])
    assert "ES6.3.9" in html and "Expected to land: ~1.9 of 2" in html
    assert "#5" in html and "In Review: 1" in html and "the stream" in html


def test_render_coming_other_tier_and_item_error():
    line = {"key": "gcp", "label": "GCP"}
    ok_html = emf_publish.build_coming_html(_cfg(), line, COMING_OK["releases"][1:])
    assert "Other: 1" in ok_html                              # 'other' tier counted
    rel = {"name": "GCP-26Q2", "release_date": "2026-06-30", "days": -10,
           "items_ok": False, "items_error": "jira down"}
    err_html = emf_publish.build_coming_html(_cfg(), line, [rel])
    assert "Jira unavailable" in err_html and "jira down" in err_html


def test_publish_all_disabled():
    cfg = _cfg()
    cfg.emf = {**cfg.emf, "enabled": False}
    assert emf_publish.publish_all(cfg)["ok"] is False


def test_publish_all_no_space():
    cfg = _cfg()
    cfg.emf = {**cfg.emf, "confluence": {"enabled": True}}       # no space_id
    r = emf_publish.publish_all(cfg)
    assert not r["ok"] and "space_id" in r["error"]


def test_publish_all_client_error(monkeypatch):
    def boom(site=None):
        raise ConfluenceError("no creds")
    monkeypatch.setattr(emf_publish, "Confluence", boom)
    r = emf_publish.publish_all(_cfg())
    assert not r["ok"] and "no creds" in r["error"]


def test_publish_all_ok(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(emf_publish, "Confluence", lambda site=None: client)
    monkeypatch.setattr(emf_publish.emf, "collect_landed", lambda c: LANDED_OK)
    monkeypatch.setattr(emf_publish.emf, "collect_coming", lambda c: COMING_OK)
    r = emf_publish.publish_all(_cfg())
    assert r["ok"]
    assert [c["title"] for c in client.calls] == [
        "EMF — Landed (current build)", "EMF — Coming: Main release", "EMF — Coming: GCP"]
    assert [x["page"] for x in r["results"]] == ["landed", "coming:main", "coming:gcp"]


def test_publish_all_skips_line_without_releases(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(emf_publish, "Confluence", lambda site=None: client)
    monkeypatch.setattr(emf_publish.emf, "collect_landed", lambda c: LANDED_OK)
    # only a main-line release -> the gcp line is skipped (no page)
    monkeypatch.setattr(emf_publish.emf, "collect_coming",
                        lambda c: {"ok": True, "releases": [COMING_OK["releases"][0]]})
    r = emf_publish.publish_all(_cfg())
    assert [x["page"] for x in r["results"]] == ["landed", "coming:main"]


def test_publish_all_coming_error(monkeypatch):
    monkeypatch.setattr(emf_publish, "Confluence", lambda site=None: _FakeClient())
    monkeypatch.setattr(emf_publish.emf, "collect_landed", lambda c: LANDED_OK)
    monkeypatch.setattr(emf_publish.emf, "collect_coming", lambda c: {"ok": False, "error": "no creds"})
    r = emf_publish.publish_all(_cfg())
    assert not r["ok"]
    assert any(x.get("page") == "coming" and "no creds" in (x.get("error") or "") for x in r["results"])


def test_publish_all_upsert_error(monkeypatch):
    monkeypatch.setattr(emf_publish, "Confluence", lambda site=None: _FakeClient(fail=True))
    monkeypatch.setattr(emf_publish.emf, "collect_landed", lambda c: LANDED_OK)
    monkeypatch.setattr(emf_publish.emf, "collect_coming", lambda c: COMING_OK)
    r = emf_publish.publish_all(_cfg())
    assert not r["ok"] and all(not x["ok"] for x in r["results"])
