from lustre_reporter import util
from lustre_reporter.analysis import backport
from lustre_reporter.cli import ToolResult
from lustre_reporter.config import MasterRepo


def raw(num, subj):
    return {"number": num, "url": f"u{num}", "subject": subj, "status": "MERGED",
            "owner": "o", "tickets": util.parse_tickets(subj)}


def prepped(num, subj):
    c = raw(num, subj)
    backport._prep(c)
    return c


def test_normalize_subject():
    assert backport.normalize_subject("LU-1 EX-2 kernel: Fix It!") == "kernel fix it"
    assert backport.normalize_subject("") == ""


def test_subject_match():
    def m(a, b):
        return backport._subject_match(a, backport._tokens(a), b, backport._tokens(b))
    assert m("kernel fix", "kernel fix") is True          # equal
    assert m("kernel fix now", "kernel fix") is True      # substring
    assert m("alpha beta gamma", "gamma beta alpha") is True  # reordered -> jaccard 1.0
    assert m("kernel fix", "totally other words here") is False
    assert m("ab cd", "ef gh") is False   # non-empty norms but empty (too-short) tokens
    assert m("", "x") is False


def test_status_in_branch():
    idx = {"by_ticket": {"LU-1": [prepped(61, "LU-1 kernel: a")]}}
    assert backport.status_in_branch(prepped(1, "LU-1 kernel: a"), idx)["state"] == "ported"
    tk = backport.status_in_branch(prepped(2, "LU-1 completely unrelated words indeed"), idx)
    assert tk["state"] == "ticket_only" and len(tk["related"]) == 1
    assert backport.status_in_branch(prepped(3, "LU-9 zzz"), idx)["state"] == "missing"


def test_score():
    row = {"branches": {"es6": {"state": "ticket_only"}, "es7": {"state": "missing"}}}
    assert backport._score(row, ["es6", "es7"]) == 4
    row2 = {"branches": {"es6": {"state": "ported"}, "es7": {"state": "ported"}}}
    assert backport._score(row2, ["es6", "es7"]) == 0


def test_build_branch_index(monkeypatch):
    monkeypatch.setattr(backport.gerrit, "merged_last_days",
                        lambda p, b, d, limit=800: ToolResult(ok=True, data=[raw(1, "LU-1 kernel: a")]))
    monkeypatch.setattr(backport.gerrit, "open_changes",
                        lambda p, b, limit=400: ToolResult(ok=False, data=None, error="opn"))
    idx = backport.build_branch_index("proj", "b", 30)
    assert "LU-1" in idx["by_ticket"] and idx["count"] == 1 and idx["errors"] == ["opn"]


def test_gather_master_dedup(monkeypatch):
    def merged(p, b, d, limit=800):
        if p == "fs/lustre-release":
            return ToolResult(ok=True, data=[raw(1, "LU-1 a"), raw(2, "LU-2 b")])
        return ToolResult(ok=True, data=[raw(2, "LU-2 b"), raw(5, "LU-5 c")])  # dup #2 + new #5
    monkeypatch.setattr(backport.gerrit, "merged_last_days", merged)
    masters = [MasterRepo("community", "C", "fs/lustre-release"),
               MasterRepo("exa", "E", "ex/lustre-release")]
    g = backport.gather_master(masters, 30)
    assert {c["number"] for c in g["changes"]} == {1, 2, 5} and g["errors"] == []


def test_gather_master_error(monkeypatch):
    monkeypatch.setattr(backport.gerrit, "merged_last_days",
                        lambda p, b, d, limit=800: ToolResult(ok=False, data=None, error="exa boom"))
    g = backport.gather_master([MasterRepo("exa", "E", "ex/lustre-release")], 30)
    assert g["changes"] == [] and "exa boom" in g["errors"][0]


def _wire(monkeypatch):
    def merged(project, branch, days, limit=800):
        table = {
            ("fs/lustre-release", "master"): [raw(1, "LU-1 kernel: a"), raw(2, "LU-2 pcc: b"),
                                              raw(3, "LU-3 tests: add interop check"),
                                              raw(4, "LU-4 build: shared thing")],
            ("ex/lustre-release", "master"): [],
            ("ex/lustre-release", "b_es6_0"): [raw(61, "LU-1 kernel: a"),
                                               raw(63, "LU-3 tests: skip flaky case"),
                                               raw(64, "LU-4 build: shared thing")],
            ("ex/lustre-release", "b_es7_0"): [raw(74, "LU-4 build: shared thing")],
        }
        return ToolResult(ok=True, data=table.get((project, branch), []))
    monkeypatch.setattr(backport.gerrit, "merged_last_days", merged)
    monkeypatch.setattr(backport.gerrit, "open_changes",
                        lambda p, b, limit=400: ToolResult(ok=True, data=[]))


def test_analyze_gaps_only(monkeypatch, cfg):
    _wire(monkeypatch)
    r = backport.analyze(cfg, 30)
    assert r["master_changes_scanned"] == 4
    nums = {c["number"] for c in r["candidates"]}
    assert nums == {1, 2, 3}                      # LU-4 ported on both → excluded
    assert r["candidate_count"] == 3 and r["truncated"] is False
    assert r["counts"]["es6"] == {"missing": 1, "ticket_only": 1, "ported": 2}
    assert r["counts"]["es7"] == {"missing": 3, "ticket_only": 0, "ported": 1}
    assert r["candidates"][0]["number"] == 3      # highest score (ticket_only + missing)
    assert r["errors"] == []


def test_analyze_all_patches(monkeypatch, cfg):
    _wire(monkeypatch)
    r = backport.analyze(cfg, 30, only_gaps=False)
    assert 4 in {c["number"] for c in r["candidates"]}   # ported LU-4 shown when not gaps-only


def test_analyze_truncation(monkeypatch, cfg):
    _wire(monkeypatch)
    r = backport.analyze(cfg, 30, max_rows=1)
    assert r["truncated"] is True and len(r["candidates"]) == 1


def test_analyze_collects_errors(monkeypatch, cfg):
    monkeypatch.setattr(backport.gerrit, "merged_last_days",
                        lambda p, b, d, limit=800: ToolResult(ok=False, data=None, error="boom"))
    monkeypatch.setattr(backport.gerrit, "open_changes",
                        lambda p, b, limit=400: ToolResult(ok=False, data=None, error="opn"))
    r = backport.analyze(cfg, 30)
    assert r["candidate_count"] == 0 and r["errors"]


def test_status_in_branch_iterates_related():
    idx = {"by_ticket": {"LU-1": [prepped(60, "LU-1 unrelated words entirely"),
                                  prepped(61, "LU-1 kernel: a")]}}
    st = backport.status_in_branch(prepped(1, "LU-1 kernel: a"), idx)
    assert st["state"] == "ported" and st["change"]["number"] == 61


def test_build_branch_index_okfalse_no_error(monkeypatch):
    # ok=False but error=None -> neither branch appends (covers the elif-false arc)
    monkeypatch.setattr(backport.gerrit, "merged_last_days",
                        lambda p, b, d, limit=800: ToolResult(ok=False, data=None, error=None))
    monkeypatch.setattr(backport.gerrit, "open_changes",
                        lambda p, b, limit=400: ToolResult(ok=True, data=[]))
    assert backport.build_branch_index("p", "b", 30)["errors"] == []
