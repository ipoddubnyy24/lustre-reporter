import pytest

from lustre_reporter import emf
from lustre_reporter.cli import ToolResult
from lustre_reporter.config import Config


def okt(data):
    return ToolResult(ok=True, data=data)


def _cfg():
    return Config()


@pytest.fixture(autouse=True)
def _fresh_caches(monkeypatch):
    monkeypatch.setattr(emf, "_FAILED_JOBS", {})
    monkeypatch.setattr(emf, "_ANALYSES", {})


def test_release_line():
    lines = _cfg().emf["release_lines"]
    assert emf.release_line("ES6.3.9", lines)["key"] == "main"
    assert emf.release_line("GCP-26Q2", lines)["key"] == "gcp"
    assert emf.release_line("Weird-1", lines) is None
    assert emf.release_line(None, lines) is None


def test_collect_stability_ok(monkeypatch):
    monkeypatch.setattr(emf.github, "workflow_runs",
                        lambda repo, wf, **k: okt([{"conclusion": "success", "created_at": "2026-07-10T00:00:00Z"}]))
    r = emf.collect_stability(_cfg(), days=30)
    assert r["ok"] and r["summary"]["runs"] == 1 and r["days"] == 30 and r["from"] is None


def test_collect_stability_default_days_error(monkeypatch):
    monkeypatch.setattr(emf.github, "workflow_runs",
                        lambda repo, wf, **k: ToolResult(ok=False, data=None, error="x", kind="auth"))
    r = emf.collect_stability(_cfg())                # days defaults to cfg.emf.stability_days (30)
    assert not r["ok"] and r["days"] == 30 and r["kind"] == "auth"


def test_collect_stability_custom_range(monkeypatch):
    seen = {}

    def wf(repo, workflow, *, since=None, until=None, **k):
        seen["since"], seen["until"] = since, until
        return okt([{"conclusion": "success", "created_at": "2026-05-10T00:00:00Z"},   # in window
                    {"conclusion": "failure", "created_at": "2026-01-01T00:00:00Z"}])   # before frm
    monkeypatch.setattr(emf.github, "workflow_runs", wf)
    r = emf.collect_stability(_cfg(), days=40, frm="2026-05-01", to="2026-06-01")
    assert seen == {"since": "2026-05-01", "until": "2026-06-01"}
    assert r["from"] == "2026-05-01" and r["to"] == "2026-06-01"
    assert r["summary"]["runs"] == 1                 # out-of-window run dropped by the defensive bound


def test_collect_landed(monkeypatch):
    seen = {}
    monkeypatch.setattr(emf.github, "default_branch", lambda repo: okt({"name": "master"}))
    monkeypatch.setattr(emf.jira, "fix_versions", lambda keys: okt({}))
    monkeypatch.setattr(emf.github, "landed", lambda repo, branch, tag=None: seen.update(branch=branch) or {
        "ok": True, "patches": [{"tickets": [{"key": "EX-1", "project": "EX"},
                                             {"key": "LU-2", "project": "LU"}]}]})
    ts = emf.collect_landed(_cfg(), tag="T")["patches"][0]["tickets"]
    assert seen["branch"] == "master"            # release_branch unset: the repo's default branch
    assert ts[0]["url"].endswith("/EX-1") and ts[0]["is_cloud"] is True
    assert ts[1]["is_cloud"] is False


def _landed_with(monkeypatch, subjects, fixes):
    monkeypatch.setattr(emf.github, "default_branch", lambda repo: okt({"name": "master"}))
    monkeypatch.setattr(emf.github, "landed", lambda repo, branch, tag=None: {
        "ok": True, "patches": [{"number": n, "tickets": emf.util.parse_tickets(s)}
                                for n, s in enumerate(subjects)]})
    asked = []
    monkeypatch.setattr(emf.jira, "fix_versions", lambda keys: asked.extend(keys) or fixes)
    return asked


def test_collect_landed_splits_by_product(monkeypatch):
    asked = _landed_with(monkeypatch, [
        "EX-1: both lines",          # ES6.3.10 + ES7.0.0_Beta -> exa6 and exa7
        "EXM-2: nvmesh",             # project -> sd
        "GCP-3 google",              # project -> gcp
        "EX-4: gcp quarter",         # fixVersion GCP-26Q3 -> gcp
        "EX-5: no fix version",      # -> unassigned
        "Fix cargo deny (#5979)"],   # no ticket -> unassigned
        okt({"EX-1": ["ES6.3.10", "ES7.0.0_Beta"], "EX-4": ["GCP-26Q3"], "EX-5": []}))
    r = emf.collect_landed(_cfg())
    assert asked == ["EX-1", "EX-4", "EX-5"]                       # only EX keys are looked up
    assert [p["products"] for p in r["patches"]] == [["exa6", "exa7"], ["sd"], ["gcp"], ["gcp"], [], []]
    assert [(x["label"], x["count"]) for x in r["products"]] == [
        ("EXA6", 1), ("EXA7", 1), ("EXA SD", 1), ("EXA GCP", 2)]   # config order, EXA6 first
    assert r["unassigned"] == 2 and "products_error" not in r
    assert r["patches"][1]["tickets"][0]["is_cloud"] is True       # EXM links go to Jira Cloud


def test_collect_landed_fix_versions_error(monkeypatch):
    _landed_with(monkeypatch, ["EX-1: x", "EXM-2: y"],
                 ToolResult(ok=False, data=None, error="jira down", kind="error"))
    r = emf.collect_landed(_cfg())
    assert r["products_error"] == "jira down"
    assert [p["products"] for p in r["patches"]] == [[], ["sd"]]   # EX unassigned, EXM still by project


def test_collect_landed_without_products(monkeypatch):
    cfg = _cfg()
    cfg.emf = {**cfg.emf, "products": []}
    _landed_with(monkeypatch, ["EX-1: x"], okt({}))
    r = emf.collect_landed(cfg)
    assert "products" not in r and "products" not in r["patches"][0]


def test_collect_landed_configured_branch(monkeypatch):
    cfg, seen, lookups = _cfg(), {}, []
    cfg.emf = {**cfg.emf, "release_branch": "release/sfa-next"}
    monkeypatch.setattr(emf.github, "default_branch", lambda repo: lookups.append(repo) or okt({"name": "x"}))
    monkeypatch.setattr(emf.github, "landed",
                        lambda repo, branch, tag=None: seen.update(branch=branch) or {"ok": True, "patches": []})
    assert emf.collect_landed(cfg)["ok"]
    assert seen["branch"] == "release/sfa-next" and lookups == []


def test_collect_landed_default_branch_error(monkeypatch):
    monkeypatch.setattr(emf.github, "default_branch",
                        lambda repo: ToolResult(ok=False, data=None, error="x", kind="auth"))
    r = emf.collect_landed(_cfg())
    assert not r["ok"] and r["kind"] == "auth"


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
        {"name": "ES2018", "release_date": "2018-01-01", "released": False},    # dropped by grace
        {"name": "GCP-26Q3", "release_date": None, "released": False}],         # undated: not forecast
        search_map={"GCP-26Q2": okt([{"key": "EX-9", "status": "In Progress", "summary": "g"}]),
                    "ES6.3.9": okt([{"key": "EX-1", "status": "In Review", "summary": "m"}])},
        prs=[{"number": 5, "url": "pr5", "isDraft": False, "title": "EX-1 fix", "headRefName": "x"}])
    monkeypatch.setattr(emf.forecast, "days_until",
                        lambda d, **k: {"2026-06-30": -10, "2026-09-04": 56, "2018-01-01": -3000}.get(d))
    r = emf.collect_coming(_cfg())
    assert [(x["name"], x["line"]) for x in r["releases"]] == [("ES6.3.9", "main"), ("GCP-26Q2", "gcp")]
    assert r["releases"][0]["line_label"] == "Main release"
    assert r["releases"][0]["items"][0]["prs"][0]["number"] == 5
    assert [(u["name"], u["line"], u["days"]) for u in r["untracked"]] == [
        ("GCP-26Q3", "gcp", None), ("ES2018", "main", -3000)]        # undated first, then newest


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


# ---------------- nightly failures: common reasons + per-run analysis ----------------
RUNS = [
    {"id": 3, "run_number": 3, "conclusion": "failure", "created_at": "2026-10-27T01:00:00Z", "url": "u3",
     "head_sha": "c3"},
    {"id": 2, "run_number": 2, "conclusion": "success", "created_at": "2026-10-25T01:00:00Z", "url": "u2",
     "head_sha": "c2"},
    {"id": 1, "run_number": 1, "conclusion": "failure", "created_at": "2026-10-24T01:00:00Z", "url": "u1",
     "head_sha": "c1"},
    {"id": 4, "run_number": 4, "conclusion": "success", "created_at": "2026-10-28T01:00:00Z", "url": "u4",
     "head_sha": "c4"},                                               # after run 3: not its last success
]
JOBS = {3: [{"id": 30, "name": "smoke (a) / provision", "url": "j30", "failed_steps": ["upgrade", "SOS"]}],
        1: [{"id": 10, "name": "smoke (b) / provision", "url": "j10", "failed_steps": ["upgrade"]}]}
LOGTEXT = "j\ts\t2026-10-27T01:00:00Z Waiting for stonith\nj\ts\t2026-10-27T01:00:01Z ##[error]Process completed with exit code 1."


def _wire(monkeypatch, *, runs=RUNS, run=None, logs=None, compare=None):
    calls = {"jobs": [], "window": [], "run": 0, "compare": 0}

    def wf(repo, workflow, *, since=None, until=None, **k):
        calls["window"].append((since, until))
        return runs if isinstance(runs, ToolResult) else okt(runs)

    def fj(repo, rid):
        calls["jobs"].append(rid)
        return okt(JOBS[rid]) if rid in JOBS else ToolResult(ok=False, data=None, error="HTTP 502")

    def rn(repo, rid):
        calls["run"] += 1
        return run or okt({**RUNS[0], "run_attempt": 1, "status": "completed", "event": "schedule"})

    def cmp(repo, base, head):
        calls["compare"] += 1
        return compare or okt({"total": 1, "commits": [{"sha": "c3", "message": "EX-1 x", "author": "A", "url": "cu"}]})
    monkeypatch.setattr(emf.github, "workflow_runs", wf)
    monkeypatch.setattr(emf.github, "failed_jobs", fj)
    monkeypatch.setattr(emf.github, "run", rn)
    monkeypatch.setattr(emf.github, "failed_log", lambda repo, jid: (logs or {}).get(jid, okt(LOGTEXT)))
    monkeypatch.setattr(emf.github, "compare", cmp)
    return calls


def test_collect_failure_reasons(monkeypatch):
    calls = _wire(monkeypatch, runs=RUNS + [{"id": 5, "conclusion": "failure", "created_at": "2026-10-20"}])
    r = emf.collect_failure_reasons(_cfg(), days=30)
    assert r["ok"] and r["failed"] == 3 and r["read"] == 2 and r["errors"] == 1     # run 5's lookup failed
    assert [(g["signature"], g["count"]) for g in r["reasons"]] == [("smoke / provision › upgrade", 2)]
    emf.collect_failure_reasons(_cfg(), days=30)
    assert sorted(calls["jobs"]) == [1, 3, 5, 5]                     # read once per run; failures retried


def test_collect_failure_reasons_error(monkeypatch):
    _wire(monkeypatch, runs=ToolResult(ok=False, data=None, error="gh 401", kind="auth"))
    r = emf.collect_failure_reasons(_cfg())
    assert not r["ok"] and r["kind"] == "auth"


def test_analyze_run_full_and_cached(monkeypatch):
    calls = _wire(monkeypatch)
    r = emf.analyze_run(_cfg(), 3)
    assert r["ok"] and r["complete"] and r["filename"] == "emf-nightly-3-analysis.md" and r["url"] == "u3"
    assert calls["window"] == [("2026-09-28", "2026-10-27")]         # the 30 days up to the run
    md = r["markdown"]
    assert "failed at *upgrade*" in md and "2 of 2 failed runs. Others: [2026-10-24](u1)" in md
    assert "**Last success:** [#2](u2)" in md and "**Commits since then:** 1" in md
    assert emf.analyze_run(_cfg(), 3) is r and calls["run"] == 1     # complete analyses are kept
    emf.analyze_run(_cfg(), 3, refresh=True)
    assert calls["run"] == 2 and calls["jobs"].count(3) == 2          # refresh re-reads the run and its jobs


def test_analyze_run_errors(monkeypatch):
    _wire(monkeypatch, run=ToolResult(ok=False, data=None, error="HTTP 404", kind="error"))
    assert emf.analyze_run(_cfg(), 3) == {"ok": False, "kind": "error", "error": "HTTP 404", "run_id": 3}
    _wire(monkeypatch, run=okt({"id": 7, "created_at": "2026-10-27T01:00:00Z"}))
    r = emf.analyze_run(_cfg(), 7)                                   # no jobs lookup for run 7 in JOBS
    assert not r["ok"] and r["error"] == "HTTP 502"


def test_analyze_run_incomplete_is_not_kept(monkeypatch):
    calls = _wire(monkeypatch, logs={30: ToolResult(ok=False, data=None, error="blob unreachable")},
                  compare=ToolResult(ok=False, data=None, error="HTTP 500"))
    r = emf.analyze_run(_cfg(), 3)
    assert r["ok"] and not r["complete"]
    assert "could not be downloaded: blob unreachable" in r["markdown"]
    assert "Changes could not be listed: HTTP 500" in r["markdown"]
    emf.analyze_run(_cfg(), 3)
    assert calls["run"] == 2                                          # not kept: fetched again


def test_analyze_run_history_error_and_same_commit(monkeypatch):
    _wire(monkeypatch, runs=ToolResult(ok=False, data=None, error="gh down"))
    r = emf.analyze_run(_cfg(), 3)
    assert "Run history unavailable: gh down" in r["markdown"] and not r["complete"]
    same = [dict(x, head_sha="c3") if x["id"] == 2 else x for x in RUNS]
    calls = _wire(monkeypatch, runs=same)
    emf.analyze_run(_cfg(), 3, refresh=True)
    assert calls["compare"] == 0                                      # same commit: nothing to compare


def test_analyze_run_without_date_or_success(monkeypatch):
    calls = _wire(monkeypatch, runs=[RUNS[0]],
                  run=okt({"id": 3, "status": "in_progress", "head_sha": "c3"}))
    r = emf.analyze_run(_cfg(), 3)
    assert calls["window"][0][1] is None                              # rolling window when the run has no date
    assert "No successful run in the 30 days" in r["markdown"] and not r["complete"]   # still running
