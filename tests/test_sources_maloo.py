from lustre_reporter.cli import ToolResult
from lustre_reporter.sources import maloo


def _ok(data):
    return ToolResult(ok=True, data=data)


def test_sessions_args_and_data(monkeypatch):
    seen = {}
    monkeypatch.setattr(maloo, "run_json",
                        lambda tool, args, **k: (seen.__setitem__("a", args), _ok({"sessions": [{"session_id": 1}]}))[1])
    r = maloo.sessions("lustre-b_es6_0", days=10, limit=5)
    assert r.data == [{"session_id": 1}]
    assert seen["a"] == ["sessions", "--branch", "lustre-b_es6_0", "--days", "10", "--limit", "5"]


def test_sessions_failed_flag(monkeypatch):
    seen = {}
    monkeypatch.setattr(maloo, "run_json",
                        lambda tool, args, **k: (seen.__setitem__("a", args), _ok({}))[1])
    maloo.sessions("j", failed=True)
    assert "--failed" in seen["a"]


def test_sessions_error_passthrough(monkeypatch):
    monkeypatch.setattr(maloo, "run_json",
                        lambda *a, **k: ToolResult(ok=False, data=None, error="401", kind="auth"))
    assert maloo.sessions("j").ok is False


def test_sessions_data_not_dict(monkeypatch):
    monkeypatch.setattr(maloo, "run_json", lambda *a, **k: _ok(["x"]))
    assert maloo.sessions("j").data == []


def test_top_failures_args(monkeypatch):
    seen = {}
    monkeypatch.setattr(maloo, "run_json",
                        lambda tool, args, **k: (seen.__setitem__("a", args), _ok({"top_failures": [{"rank": 1}]}))[1])
    r = maloo.top_failures("j", days=14, sessions=20, limit=7)
    assert r.data == [{"rank": 1}]
    assert seen["a"] == ["top-failures", "j", "--days", "14", "--sessions", "20", "--limit", "7"]


def test_top_failures_error(monkeypatch):
    monkeypatch.setattr(maloo, "run_json", lambda *a, **k: ToolResult(ok=False, data=None, error="e"))
    assert maloo.top_failures("j").ok is False
