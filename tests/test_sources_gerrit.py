from lustre_reporter.cli import ToolResult
from lustre_reporter.sources import gerrit


def _ok(data):
    return ToolResult(ok=True, data=data)


def test_search_ok_normalizes(monkeypatch):
    seen = {}

    def fake(tool, args, **k):
        seen["args"] = args
        return _ok({"changes": [{"number": 1, "subject": "LU-1 pcc: fix", "project": "p",
                                 "branch": "b", "status": "MERGED", "owner": "o",
                                 "updated": "2026-07-09", "url": "u", "size": "+1/-0"}]})
    monkeypatch.setattr(gerrit, "run_json", fake)
    r = gerrit.search("q", limit=5)
    assert r.ok and seen["args"] == ["search", "q", "-n", "5"]
    assert r.data[0]["number"] == 1 and r.data[0]["tickets"][0]["key"] == "LU-1"


def test_search_error_passthrough(monkeypatch):
    monkeypatch.setattr(gerrit, "run_json",
                        lambda *a, **k: ToolResult(ok=False, data=None, error="x", kind="auth"))
    assert gerrit.search("q").ok is False


def test_search_data_not_dict(monkeypatch):
    monkeypatch.setattr(gerrit, "run_json", lambda *a, **k: _ok(["weird"]))
    assert gerrit.search("q").data == []


def test_merged_since_builds_query(monkeypatch):
    seen = {}
    monkeypatch.setattr(gerrit, "run_json",
                        lambda tool, args, **k: (seen.__setitem__("a", args), _ok({"changes": []}))[1])
    gerrit.merged_since("ex/lustre-release", "b_es6_0", "2026-07-02", limit=9)
    assert seen["a"] == ["search",
                         "project:ex/lustre-release branch:b_es6_0 status:merged mergedafter:2026-07-02",
                         "-n", "9"]


def test_merged_last_days(monkeypatch):
    seen = {}
    monkeypatch.setattr(gerrit, "run_json",
                        lambda tool, args, **k: (seen.__setitem__("a", args), _ok({"changes": []}))[1])
    gerrit.merged_last_days("p", "b", 7)
    assert seen["a"][0] == "search" and "status:merged mergedafter:" in seen["a"][1]


def test_open_changes(monkeypatch):
    seen = {}
    monkeypatch.setattr(gerrit, "run_json",
                        lambda tool, args, **k: (seen.__setitem__("a", args), _ok({"changes": []}))[1])
    gerrit.open_changes("p", "b")
    assert seen["a"][1] == "project:p branch:b status:open"


def test_change_info(monkeypatch):
    monkeypatch.setattr(gerrit, "run_json",
                        lambda tool, args, **k: _ok({"x": 1}) if args == ["info", "URL"]
                        else ToolResult(ok=False, data=None))
    assert gerrit.change_info("URL").data == {"x": 1}


def test_verified_summary_fail_wins():
    info = {"reviewers": [{"approvals": {"Verified": " -1"}},
                          {"approvals": {"Verified": "+1"}},
                          {"approvals": {"Verified": " 0"}},
                          {"approvals": {}},
                          {"approvals": {"Verified": "junk"}}],
            "jenkins_build": "J", "current_patchset": 3}
    s = gerrit.verified_summary(info)
    assert s["verified"] == -1 and s["label"] == "V-1"
    assert s["jenkins_build"] == "J" and s["current_patchset"] == 3


def test_verified_summary_pass_zero_none():
    assert gerrit.verified_summary({"reviewers": [{"approvals": {"Verified": "+1"}}]})["label"] == "V+1"
    assert gerrit.verified_summary({"reviewers": [{"approvals": {"Verified": " 0"}}]})["label"] == "V0"
    none = gerrit.verified_summary({"reviewers": []})
    assert none["verified"] is None and none["label"] is None
