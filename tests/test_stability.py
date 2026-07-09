from lustre_reporter.analysis import stability

SESSIONS = [
    {"submission": "2026-07-09T06:00:00Z", "test_host": "h1", "test_group": "g",
     "test_name": "full", "passed": 2, "failed": 1, "aborted": 0, "total": 3,
     "session_id": 1, "url": "u1", "enforcing": True},
    {"submission": "2026-07-09T07:00:00Z", "test_host": "h2",
     "passed": 3, "failed": 0, "aborted": 0, "total": 3, "session_id": 2},
    {"submission": "2026-07-08T05:00:00Z",
     "passed": 0, "failed": 0, "aborted": 2, "total": 2, "session_id": 3},
]


def test_summarize():
    s = stability.summarize(SESSIONS)
    assert s["sessions"] == 3
    assert s["clean_sessions"] == 1        # only session 2 (0 failed, 0 aborted)
    assert s["failed_sessions"] == 2
    assert s["session_pass_rate"] == round(1 / 3 * 100, 1)
    assert (s["testsets_passed"], s["testsets_failed"], s["testsets_aborted"],
            s["testsets_total"]) == (5, 1, 2, 8)
    assert s["testset_pass_rate"] == 62.5


def test_summarize_empty():
    s = stability.summarize([])
    assert s["sessions"] == 0
    assert s["session_pass_rate"] is None and s["testset_pass_rate"] is None


def test_int_handles_bad_values():
    s = stability.summarize([{"submission": "2026-01-01", "passed": "x",
                              "failed": None, "total": "3"}])
    assert s["testsets_passed"] == 0 and s["testsets_total"] == 3


def test_trend_bucketing_sorted_and_rates():
    t = stability.trend(SESSIONS)
    assert [b["date"] for b in t] == ["2026-07-08", "2026-07-09"]
    d9 = next(b for b in t if b["date"] == "2026-07-09")
    assert d9["sessions"] == 2 and d9["clean"] == 1
    assert d9["testsets_passed"] == 5 and d9["testsets_total"] == 6
    d8 = next(b for b in t if b["date"] == "2026-07-08")
    assert d8["testset_pass_rate"] == 0.0 and d8["session_pass_rate"] == 0.0


def test_trend_skips_unknown_date():
    assert stability.trend([{"passed": 1, "total": 1}]) == []


def test_session_rows_sorted_desc():
    rows = stability.session_rows(SESSIONS)
    assert rows[0]["date"] == "2026-07-09T07:00:00Z"
    assert rows[-1]["date"] == "2026-07-08T05:00:00Z"
    assert rows[0]["clean"] is True and rows[-1]["clean"] is False


def test_report_shape():
    assert set(stability.report(SESSIONS)) == {"summary", "trend", "sessions"}
