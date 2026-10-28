from lustre_reporter.cli import ToolResult
from lustre_reporter.sources import github


def _ok(data):
    return ToolResult(ok=True, data=data)


def _err(msg="boom", kind="error"):
    return ToolResult(ok=False, data=None, error=msg, kind=kind)


def test_workflow_runs_paginates(monkeypatch):
    calls = []

    def fake(tool, args, timeout=90):
        calls.append(args)
        page = int(next(a.split("=")[1] for a in args if a.startswith("page=")))
        return _ok([{"conclusion": "success"}] * (100 if page == 1 else 1))  # full page then short
    monkeypatch.setattr(github, "run_json", fake)
    r = github.workflow_runs("o/r", "wf.yml", since="2026-01-01", per_page=100)
    assert r.ok and len(r.data) == 101 and len(calls) == 2      # stopped after the short page
    assert "created=>=2026-01-01" in calls[0]


def test_workflow_runs_hits_max_pages(monkeypatch):
    # every page full -> loop runs all max_pages and exits without an early break
    monkeypatch.setattr(github, "run_json", lambda tool, args, timeout=90: _ok([{"conclusion": "success"}]))
    r = github.workflow_runs("o/r", "wf.yml", per_page=1, max_pages=3)
    assert r.ok and len(r.data) == 3


def test_workflow_runs_error(monkeypatch):
    monkeypatch.setattr(github, "run_json",
                        lambda tool, args, timeout=90: ToolResult(ok=False, data=None, error="e", kind="auth"))
    assert not github.workflow_runs("o/r", "wf.yml").ok


def test_workflow_runs_date_windows(monkeypatch):
    calls = []
    monkeypatch.setattr(github, "run_json", lambda tool, args, timeout=90: (calls.append(args), _ok([]))[1])
    github.workflow_runs("o/r", "wf.yml", until="2026-02-01")
    github.workflow_runs("o/r", "wf.yml", since="2026-01-01", until="2026-02-01")
    assert "created=<=2026-02-01" in calls[0]
    assert "created=2026-01-01..2026-02-01" in calls[1]


def test_releases(monkeypatch):
    monkeypatch.setattr(github, "run_json", lambda tool, args, timeout=90: _ok([{"tag": "6.3.8-2026061600"}]))
    assert github.releases("o/r").ok


def test_compare(monkeypatch):
    monkeypatch.setattr(github, "run_json", lambda tool, args, timeout=90: _ok({"total": 3, "commits": []}))
    assert github.compare("o/r", "a", "b").data["total"] == 3


def test_open_prs(monkeypatch):
    seen = {}
    monkeypatch.setattr(github, "run_json",
                        lambda tool, args, timeout=90: (seen.update(a=args), _ok([{"number": 1}]))[1])
    assert github.open_prs("o/r").ok and "pr" in seen["a"] and "list" in seen["a"]


def test_parse_commit_skips_plumbing():
    assert github._parse_commit({"message": "Bump CalVer to 2026 (#1)"}, "o/r") is None
    assert github._parse_commit({"message": "Update changelog"}, "o/r") is None
    assert github._parse_commit({"message": "- Bump CalVer to 2026"}, "o/r") is None
    assert github._parse_commit({"message": ""}, "o/r") is None


def test_parse_commit_parses():
    p = github._parse_commit({"message": "EX-1 nodemap: fix (#4986)\n\nbody",
                              "author": "A", "date": "2026-07-01T00:00:00Z", "url": "cu"}, "o/r")
    assert p["number"] == 4986 and p["url"] == "https://github.com/o/r/pull/4986"
    assert p["tickets"][0]["key"] == "EX-1" and p["subsystem"] == "nodemap" and p["date"] == "2026-07-01"


def test_parse_commit_no_pr_uses_commit_url():
    p = github._parse_commit({"message": "EX-2 do a thing", "url": "cu"}, "o/r")
    assert p["number"] is None and p["url"] == "cu"


def test_areas():
    assert github._areas([{"subsystem": "a"}, {"subsystem": "a"}, {"subsystem": "b"}, {}]) == [["a", 2], ["b", 1]]


def test_landed_ok(monkeypatch):
    monkeypatch.setattr(github, "releases", lambda repo, limit=40: _ok(
        [{"tag": "T1", "published_at": "2026-06-25T00:00:00Z", "draft": False}]))
    monkeypatch.setattr(github, "compare", lambda repo, base, head: _ok({"total": 2, "commits": [
        {"message": "EX-1 x: y (#5)", "author": "A", "date": "2026-07-01T00:00:00Z"},
        {"message": "Bump CalVer to z (#6)"}]}) if head == "6.3.8" else _ok({"total": 0, "commits": []}))
    r = github.landed("o/r", "6.3.8")
    assert r["ok"] and r["tag"] == "T1" and r["tag_date"] == "2026-06-25"
    assert r["count"] == 1 and r["ahead"] == 2 and r["manual"] is False and r["in_release"] == 0


def test_landed_drops_backports_newest_first(monkeypatch):
    # T1 was cut from a release branch: it shipped #6 as backport #9, so master's
    # #6 is left out. Only backport subjects count, not PR refs in their bodies.
    monkeypatch.setattr(github, "releases", lambda repo, limit=40: _ok(
        [{"tag": "T1", "published_at": "2026-06-25", "draft": False}]))
    ahead = {"total": 3, "commits": [{"message": "EX-1 a (#5)", "date": "2026-07-01"},
                                     {"message": "EX-2 b (#6)", "date": "2026-07-02"},
                                     {"message": "EX-3 c (#7)", "date": "2026-07-03"}]}
    back = {"total": 1, "commits": [{"message": "EX-2 b (#6) (#9)\n\nsquashed EX-1 a (#5)"}]}
    monkeypatch.setattr(github, "compare", lambda repo, base, head: _ok(ahead if base == "T1" else back))
    r = github.landed("o/r", "master")
    assert [p["number"] for p in r["patches"]] == [7, 5]
    assert r["count"] == 2 and r["in_release"] == 1 and r["ahead"] == 3


def test_landed_backport_compare_fail(monkeypatch):
    monkeypatch.setattr(github, "releases", lambda repo, limit=40: _ok(
        [{"tag": "T1", "published_at": "2026-06-25", "draft": False}]))
    monkeypatch.setattr(github, "compare", lambda repo, base, head:
                        _ok({"total": 0, "commits": []}) if base == "T1" else _err("back", "auth"))
    r = github.landed("o/r", "b")
    assert not r["ok"] and r["kind"] == "auth" and r["tag"] == "T1"


def test_landed_with_tag(monkeypatch):
    monkeypatch.setattr(github, "releases", lambda repo, limit=40: _ok(
        [{"tag": "T1", "published_at": "2026-06-25", "draft": False},
         {"tag": "T0", "published_at": "2026-05-01", "draft": False}]))
    monkeypatch.setattr(github, "compare", lambda repo, base, head: _ok({"total": 0, "commits": []}))
    r = github.landed("o/r", "6.3.8", tag="T0")
    assert r["ok"] and r["tag"] == "T0" and r["tag_date"] == "2026-05-01" and r["manual"] is True


def test_landed_releases_fail(monkeypatch):
    monkeypatch.setattr(github, "releases", lambda repo, limit=40: _err("nope", "auth"))
    r = github.landed("o/r", "b")
    assert not r["ok"] and r["kind"] == "auth"


def test_landed_no_releases(monkeypatch):
    monkeypatch.setattr(github, "releases", lambda repo, limit=40: _ok([{"tag": "d", "draft": True}]))
    assert not github.landed("o/r", "b")["ok"]


def test_landed_compare_fail(monkeypatch):
    monkeypatch.setattr(github, "releases", lambda repo, limit=40: _ok(
        [{"tag": "T1", "published_at": "2026-06-25", "draft": False}]))
    monkeypatch.setattr(github, "compare", lambda repo, base, head: _err("cmp"))
    r = github.landed("o/r", "b")
    assert not r["ok"] and r["tag"] == "T1"
