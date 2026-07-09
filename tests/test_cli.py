import subprocess

from lustre_reporter import cli


def _cp(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess(args=["x"], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


def _avail(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda t: "/bin/" + t)


def test_missing_tool(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda t: None)
    r = cli.run_json("nope", ["x"])
    assert not r.ok and r.kind == "missing" and "not found" in r.error


def test_success(monkeypatch):
    _avail(monkeypatch)
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: _cp(stdout='{"a": 1}'))
    r = cli.run_json("x", ["y"])
    assert r.ok and r.data == {"a": 1} and r.error is None


def test_error_payload_auth(monkeypatch):
    _avail(monkeypatch)
    monkeypatch.setattr(cli.subprocess, "run",
                        lambda *a, **k: _cp(stdout='{"code": "API_ERROR", "message": "401 Unauthorized"}'))
    r = cli.run_json("x", ["y"])
    assert not r.ok and r.kind == "auth" and "401" in r.error


def test_error_payload_generic(monkeypatch):
    _avail(monkeypatch)
    monkeypatch.setattr(cli.subprocess, "run",
                        lambda *a, **k: _cp(stdout='{"code": "X", "message": "bad input"}'))
    r = cli.run_json("x", ["y"])
    assert not r.ok and r.kind == "error"


def test_nonzero_returncode_credential(monkeypatch):
    _avail(monkeypatch)
    monkeypatch.setattr(cli.subprocess, "run",
                        lambda *a, **k: _cp(returncode=2, stderr="credential problem"))
    r = cli.run_json("x", ["y"])
    assert not r.ok and r.kind == "auth"


def test_no_output(monkeypatch):
    _avail(monkeypatch)
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: _cp(stdout=""))
    r = cli.run_json("x", ["y"])
    assert not r.ok and "no parseable JSON" in r.error


def test_invalid_json(monkeypatch):
    _avail(monkeypatch)
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: _cp(stdout="not json"))
    assert cli.run_json("x", ["y"]).ok is False


def test_timeout(monkeypatch):
    _avail(monkeypatch)

    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="x", timeout=1)
    monkeypatch.setattr(cli.subprocess, "run", boom)
    r = cli.run_json("x", ["y"], timeout=1)
    assert not r.ok and "timed out" in r.error and r.kind == "error"


def test_classify_variants():
    assert cli._classify({"message": "403 Forbidden"}, "")[0] == "auth"
    assert cli._classify({"error": "unauthorized"}, "")[0] == "auth"
    assert cli._classify(None, "")[0] == "error"
    assert cli._classify({"message": "boom"}, "")[0] == "error"


def test_tool_error_attrs():
    e = cli.ToolError("gerrit", "boom", kind="auth")
    assert str(e) == "boom" and e.tool == "gerrit" and e.kind == "auth"
