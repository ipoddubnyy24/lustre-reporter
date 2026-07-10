from lustre_reporter.analysis import emf_stability

RUNS = [
    {"conclusion": "success", "created_at": "2026-07-10T01:00:00Z", "head_branch": "master",
     "event": "schedule", "url": "u1"},
    {"conclusion": "failure", "created_at": "2026-07-10T02:00:00Z", "head_branch": "master", "url": "u2"},
    {"conclusion": "failure", "created_at": "2026-07-09T01:00:00Z"},
    {"conclusion": "cancelled", "created_at": "2026-07-09T02:00:00Z"},
    {"conclusion": None, "status": "in_progress", "created_at": None},   # no date -> dropped from trend
]


def test_summarize():
    s = emf_stability.summarize(RUNS, days=30)
    assert s["runs"] == 5 and s["passed"] == 1 and s["failed"] == 2
    assert s["other"] == 2 and s["pass_rate"] == 33.3 and s["days"] == 30


def test_summarize_rate_none_when_no_decisive_runs():
    assert emf_stability.summarize([{"conclusion": "cancelled", "created_at": "x"}])["pass_rate"] is None


def test_trend():
    t = emf_stability.trend(RUNS)
    assert [b["date"] for b in t] == ["2026-07-09", "2026-07-10"]   # sorted, null-date dropped
    d10 = t[1]
    assert d10["runs"] == 2 and d10["passed"] == 1 and d10["failed"] == 1 and d10["pass_rate"] == 50.0
    assert t[0]["pass_rate"] == 0.0                                 # 0 passed / 1 failed (+1 cancelled)


def test_run_rows():
    rows = emf_stability.run_rows(RUNS, limit=3)
    assert len(rows) == 3
    assert rows[0]["date"] == "2026-07-10T02:00:00Z"               # newest first
    # conclusion falls back to status when conclusion is None (the null-date run sorts last)
    assert emf_stability.run_rows(RUNS)[-1]["conclusion"] == "in_progress"


def test_report():
    r = emf_stability.report(RUNS, days=14)
    assert set(r) == {"summary", "trend", "runs"} and r["summary"]["days"] == 14
