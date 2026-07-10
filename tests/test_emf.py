from lustre_reporter import emf
from lustre_reporter.cli import ToolResult
from lustre_reporter.config import Config


def okt(data):
    return ToolResult(ok=True, data=data)


def _cfg():
    return Config()


def test_release_line():
    lines = _cfg().emf["release_lines"]
    assert emf.release_line("ES6.3.9", lines)["key"] == "main"
    assert emf.release_line("GCP-26Q2", lines)["key"] == "gcp"
    assert emf.release_line("Weird-1", lines) is None
    assert emf.release_line(None, lines) is None


def test_collect_stability_ok(monkeypatch):
    monkeypatch.setattr(emf.github, "workflow_runs", lambda repo, wf, limit=100: okt([
        {"conclusion": "success", "created_at": "2026-07-10T00:00:00Z"},
        {"conclusion": "failure", "created_at": "2020-01-01T00:00:00Z"}]))   # old -> filtered
    monkeypatch.setattr(emf.util, "days_ago_iso", lambda d: "2026-01-01")
    r = emf.collect_stability(_cfg(), days=30)
    assert r["ok"] and r["summary"]["runs"] == 1 and r["days"] == 30


def test_collect_stability_default_days_error(monkeypatch):
    monkeypatch.setattr(emf.github, "workflow_runs",
                        lambda repo, wf, limit=100: ToolResult(ok=False, data=None, error="x", kind="auth"))
    r = emf.collect_stability(_cfg())                # days defaults to cfg.emf.stability_days (30)
    assert not r["ok"] and r["days"] == 30 and r["kind"] == "auth"


def test_collect_landed(monkeypatch):
    monkeypatch.setattr(emf.github, "landed", lambda repo, branch, tag=None: {
        "ok": True, "patches": [{"tickets": [{"key": "EX-1", "project": "EX"},
                                             {"key": "LU-2", "project": "LU"}]}]})
    ts = emf.collect_landed(_cfg(), tag="T")["patches"][0]["tickets"]
    assert ts[0]["url"].endswith("/EX-1") and ts[0]["is_cloud"] is True
    assert ts[1]["is_cloud"] is False


def _wire_coming(monkeypatch, versions, *, search_map=None, prs=None):
    monkeypatch.setattr(emf.jira, "versions", lambda p: okt(versions))
    monkeypatch.setattr(emf.github, "open_prs", lambda repo: okt(prs) if prs is not None else okt([]))

    def _search(jql, cloud=True, limit=200):
        for name, res in (search_map or {}).items():
            if ('"%s"' % name) in jql:
                return res
        return okt([])
    monkeypatch.setattr(emf.jira, "search", _search)


def test_collect_coming_auto_grouping(monkeypatch):
    _wire_coming(monkeypatch, [
        {"name": "GCP-26Q2", "release_date": "2026-06-30", "released": False, "overdue": True},
        {"name": "ES6.3.9", "release_date": "2026-09-04", "released": False, "overdue": False},
        {"name": "ES2018", "release_date": "2018-01-01", "released": False}],   # dropped by grace
        search_map={"GCP-26Q2": okt([{"key": "EX-9", "status": "In Progress", "summary": "g"}]),
                    "ES6.3.9": okt([{"key": "EX-1", "status": "In Review", "summary": "m"}])},
        prs=[{"number": 5, "url": "pr5", "isDraft": False, "title": "EX-1 fix", "headRefName": "x"}])
    monkeypatch.setattr(emf.forecast, "days_until",
                        lambda d, **k: {"2026-06-30": -10, "2026-09-04": 56, "2018-01-01": -3000}.get(d))
    r = emf.collect_coming(_cfg())
    assert [(x["name"], x["line"]) for x in r["releases"]] == [("ES6.3.9", "main"), ("GCP-26Q2", "gcp")]
    assert r["releases"][0]["line_label"] == "Main release"
    assert r["releases"][0]["items"][0]["prs"][0]["number"] == 5


def test_collect_coming_tracked_and_item_error(monkeypatch):
    cfg = _cfg()
    cfg.emf = {**cfg.emf, "track_versions": ["ES6.3.9"]}
    _wire_coming(monkeypatch, [
        {"name": "ES6.3.9", "release_date": "2026-09-04", "released": False},
        {"name": "GCP-26Q2", "release_date": "2026-06-30", "released": False}],
        search_map={"ES6.3.9": ToolResult(ok=False, data=None, error="jira down")})
    monkeypatch.setattr(emf.forecast, "days_until", lambda d, **k: 56)
    r = emf.collect_coming(cfg)
    assert [x["name"] for x in r["releases"]] == ["ES6.3.9"]          # only tracked
    assert r["releases"][0]["items_ok"] is False and "jira down" in r["releases"][0]["items_error"]


def test_collect_coming_prs_fail(monkeypatch):
    cfg = _cfg()
    cfg.emf = {**cfg.emf, "track_versions": ["ES6.3.9"]}
    _wire_coming(monkeypatch, [{"name": "ES6.3.9", "release_date": "2026-09-04", "released": False}],
                 search_map={"ES6.3.9": okt([{"key": "EX-1", "status": "To Do", "summary": "m"}])})
    monkeypatch.setattr(emf.github, "open_prs", lambda repo: ToolResult(ok=False, data=None, error="no gh"))
    monkeypatch.setattr(emf.forecast, "days_until", lambda d, **k: 56)
    r = emf.collect_coming(cfg)
    assert r["releases"][0]["items"][0]["prs"] == []                 # no enrichment when gh fails


def test_collect_coming_versions_error(monkeypatch):
    monkeypatch.setattr(emf.jira, "versions",
                        lambda p: ToolResult(ok=False, data=None, error="no creds", kind="error"))
    r = emf.collect_coming(_cfg())
    assert not r["ok"] and "no creds" in r["error"]
