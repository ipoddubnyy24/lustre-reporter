from lustre_reporter.cli import ToolResult
from lustre_reporter.sources import jira


def _ok(data):
    return ToolResult(ok=True, data=data)


def test_get_lu_no_cloud_flag(monkeypatch):
    seen = {}
    monkeypatch.setattr(jira, "run_json",
                        lambda tool, args, **k: (seen.__setitem__("a", args), _ok({"key": "LU-1", "status": "Open"}))[1])
    r = jira.get("LU-1")
    assert r.ok and r.data["key"] == "LU-1" and "-I" not in seen["a"]


def test_get_cloud_flag(monkeypatch):
    seen = {}
    monkeypatch.setattr(jira, "run_json",
                        lambda tool, args, **k: (seen.__setitem__("a", args), _ok({"key": "EX-1"}))[1])
    jira.get("EX-1", cloud=True)
    assert "-I" in seen["a"] and "cloud" in seen["a"]


def test_get_error_passthrough(monkeypatch):
    monkeypatch.setattr(jira, "run_json",
                        lambda *a, **k: ToolResult(ok=False, data=None, error="e", kind="auth"))
    assert jira.get("LU-1").ok is False


def test_get_non_dict_payload(monkeypatch):
    monkeypatch.setattr(jira, "run_json", lambda *a, **k: _ok(["x"]))
    r = jira.get("LU-1")
    assert r.ok is False and "unexpected" in r.error


def test_search_issues_key(monkeypatch):
    monkeypatch.setattr(jira, "run_json", lambda *a, **k: _ok({"issues": [{"key": "LU-1"}, {"key": "LU-2"}]}))
    assert [i["key"] for i in jira.search("q").data] == ["LU-1", "LU-2"]


def test_search_bare_list(monkeypatch):
    monkeypatch.setattr(jira, "run_json", lambda *a, **k: _ok([{"key": "X-1"}]))
    assert jira.search("q", cloud=True).data[0]["key"] == "X-1"


def test_search_weird_payload(monkeypatch):
    monkeypatch.setattr(jira, "run_json", lambda *a, **k: _ok({"nope": 1}))
    assert jira.search("q").data == []


def test_search_error(monkeypatch):
    monkeypatch.setattr(jira, "run_json", lambda *a, **k: ToolResult(ok=False, data=None, error="e"))
    assert jira.search("q").ok is False


def test_normalize_flatten_objects_and_lists():
    n = jira.normalize({
        "key": "LU-1", "summary": "s", "status": {"name": "Open"},
        "priority": {"name": "Major"}, "assignee": {"displayName": "Al"},
        "reporter": "bob", "issuetype": {"name": "Bug"}, "resolution": None,
        "labels": ["a", "b"], "fixVersions": [{"name": "2.16"}, {"name": "2.17"}],
        "updated": "u",
    })
    assert n["status"] == "Open" and n["priority"] == "Major"
    assert n["assignee"] == "Al" and n["reporter"] == "bob" and n["issue_type"] == "Bug"
    assert n["labels"] == ["a", "b"] and n["fix_versions"] == ["2.16", "2.17"]
    assert n["resolution"] is None


def test_normalize_non_list_labels_and_versions():
    n = jira.normalize({"key": "LU-2", "labels": "notlist", "fixVersions": "x"})
    assert n["labels"] == [] and n["fix_versions"] == "x"  # non-list fixVersions passthrough


def test_flatten_edge_cases():
    assert jira._flatten(None) is None
    assert jira._flatten("x") == "x"
    assert jira._flatten({"name": "N"}, "name") == "N"
    assert jira._flatten({"other": "o"}, "name") == "{'other': 'o'}"
    assert jira._flatten(5) == "5"


def test_search_scalar_payload(monkeypatch):
    monkeypatch.setattr(jira, "run_json", lambda *a, **k: ToolResult(ok=True, data=42))
    assert jira.search("q").data == []


def test_versions_ok(monkeypatch):
    monkeypatch.setattr(jira.atlassian, "cloud_get", lambda path: [
        {"name": "ES6.3.9", "releaseDate": "2026-09-04", "released": False, "overdue": False},
        {"name": "old", "released": True}, "junk"])
    r = jira.versions("EX")
    assert r.ok and len(r.data) == 2
    assert r.data[0] == {"name": "ES6.3.9", "release_date": "2026-09-04",
                         "released": False, "overdue": False}


def test_versions_error(monkeypatch):
    def boom(path):
        raise jira.atlassian.AtlassianError("boom")
    monkeypatch.setattr(jira.atlassian, "cloud_get", boom)
    r = jira.versions("EX")
    assert not r.ok and "boom" in r.error


def test_versions_bad_payload(monkeypatch):
    monkeypatch.setattr(jira.atlassian, "cloud_get", lambda path: {"not": "a list"})
    assert not jira.versions("EX").ok
