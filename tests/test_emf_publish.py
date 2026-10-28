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
    assert "commits merged onto EMF (" in html and "6.3.8" not in html


def test_render_landed_notes_backports():
    html = emf_publish.build_landed_html(_cfg(), {**LANDED_OK, "in_release": 37})
    assert "Already in T as backports, so not listed: 37." in html


def test_render_landed_split_by_product():
    p = LANDED_OK["patches"][0]
    landed = {**LANDED_OK, "count": 3,
              "patches": [{**p, "products": ["exa6", "exa7"]}, {**p, "number": 6, "products": ["sd"]},
                          {**p, "number": 7, "products": []}],
              "products": [{"key": "exa6", "label": "EXA6", "note": "EX fixVersion ES6.x", "count": 1},
                           {"key": "exa7", "label": "EXA7", "note": "EX fixVersion ES7.x", "count": 1},
                           {"key": "sd", "label": "EXA SD", "note": "EXM tickets", "count": 1},
                           {"key": "gcp", "label": "EXA GCP", "count": 0}]}
    html = emf_publish.build_landed_html(_cfg(), landed)
    heads = ["<h3>EXA6 (1)</h3>", "<h3>EXA7 (1)</h3>", "<h3>EXA SD (1)</h3>", "<h3>EXA GCP (0)</h3>",
             "<h3>Not assigned to a product (1)</h3>"]
    assert all(h in html for h in heads)
    assert [html.index(h) for h in heads] == sorted(html.index(h) for h in heads)   # EXA6 first
    assert "EXA6 = EX fixVersion ES6.x" in html and "EXA GCP =" not in html          # note only when set
    assert "Jira fixVersions unavailable" not in html
    err = emf_publish.build_landed_html(_cfg(), {**landed, "products_error": "jira down"})
    assert "Jira fixVersions unavailable:</strong> jira down" in err


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


def test_publish_all_no_targets():
    cfg = _cfg()
    cfg.emf = {**cfg.emf, "confluence": {"enabled": True}}       # no targets, no space_id
    r = emf_publish.publish_all(cfg)
    assert not r["ok"] and "targets" in r["error"]


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
    # 3 pages × 2 targets (personal + EXAScaler-ENG)
    assert len(client.calls) == 6
    assert {c["title"] for c in client.calls} == {
        "EMF — Landed (current build)", "EMF — Incoming: Main release", "EMF — Incoming: GCP"}
    assert {x["page"] for x in r["results"]} == {"landed", "coming:main", "coming:gcp"}
    assert {x["space"] for x in r["results"]} == {"1075183618", "3669721108"}   # both destinations


def test_publish_all_line_without_releases_still_published(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(emf_publish, "Confluence", lambda site=None: client)
    monkeypatch.setattr(emf_publish.emf, "collect_landed", lambda c: LANDED_OK)
    # only a main-line release: the gcp page is still refreshed, naming the undated version
    monkeypatch.setattr(emf_publish.emf, "collect_coming", lambda c: {
        "ok": True, "releases": [COMING_OK["releases"][0]],
        "untracked": [{"name": "GCP-26Q3", "release_date": None, "days": None, "line": "gcp"},
                      {"name": "ES2018", "release_date": "2018-01-01", "days": -3000, "line": "main"}]})
    r = emf_publish.publish_all(_cfg())
    assert {x["page"] for x in r["results"]} == {"landed", "coming:main", "coming:gcp"}
    assert len(r["results"]) == 6                                          # 3 pages × 2 targets
    gcp = next(c["html"] for c in client.calls if c["title"] == "EMF — Incoming: GCP")
    assert "No upcoming GCP release to forecast" in gcp and "GCP-26Q3 (date TBD)" in gcp
    assert "ES2018" not in gcp                                             # other lines' versions stay off
    main = next(c["html"] for c in client.calls if c["title"] == "EMF — Incoming: Main release")
    assert "No upcoming" not in main and "ES6.3.9" in main


def test_render_coming_no_releases_no_untracked():
    html = emf_publish.build_coming_html(_cfg(), {"key": "gcp", "label": "GCP"}, [])
    assert "No upcoming GCP release to forecast" in html and "later than 30 days ago" in html
    assert "Unreleased but not forecast" not in html


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
