from lustre_reporter.analysis import emf_failure as ef


def _log(*messages, job="nightly / job (rocky)", step="UNKNOWN STEP"):
    return "\n".join(f"{job}\t{step}\t2026-10-27T12:23:15.2437541Z {m}" for m in messages)


LOG = _log(
    "##[start-action display=Start Cluster;id=__self.__run_7]",
    "\x1b[1;31mWaiting for stonith-co-es-pm-155\x1b[0m",
    *["Waiting for stonith-co-es-pm-155"] * 3,
    "Error occurred: Operation for resource stonith-co-es-pm-155 exceeds timeout.",
    "##[error]Process completed with exit code 1.",
    "##[end-action id=__self.__run_7;outcome=failure;conclusion=failure;duration_ms=631207]",
    "##[start-action display=Mount Filesystem;id=__self.__run_8]",
    "##[end-action id=__self.__run_8;outcome=skipped;conclusion=skipped;duration_ms=0]",
    "##[error]Process completed with exit code 2.",
)


def test_signature_drops_matrix_values():
    assert ef.signature("nightly_iso_build / ES ISO (rhel, 6.3.9) / provision", ["Create ISO", "SOS"]) == \
        "nightly_iso_build / ES ISO / provision › Create ISO"
    assert ef.signature(None, []) == "(unnamed job) › (no failed step reported)"


def test_parse_log_finds_action_error_and_context():
    p = ef.parse_log(LOG)
    assert p["actions"] == ["Start Cluster"]                        # skipped action is not a failure
    assert p["error"] == "Process completed with exit code 1." and p["exit_code"] == 1   # first error only
    assert p["excerpt"] == ["Waiting for stonith-co-es-pm-155  (×4)",                    # colours stripped, folded
                            "Error occurred: Operation for resource stonith-co-es-pm-155 exceeds timeout."]
    assert p["key_lines"] == ["Error occurred: Operation for resource stonith-co-es-pm-155 exceeds timeout."]


def test_parse_log_without_error_marker_or_exit_code():
    assert ef.parse_log(None) == {"actions": [], "error": None, "exit_code": None, "key_lines": [], "excerpt": []}
    p = ef.parse_log("plain line without tabs\n##[error]Something broke\n"
                     "##[end-action id=unknown;outcome=failure]")
    assert p["error"] == "Something broke" and p["exit_code"] is None
    assert p["excerpt"] == ["plain line without tabs"] and p["actions"] == ["unknown"]   # unnamed action: its id


def test_classify_uses_line_closest_to_error():
    assert ef.classify(ef.parse_log(LOG)) == "Timeout"
    late = {"key_lines": ["SSH_TIMEOUT: 30"], "excerpt": ["cp: cannot stat 'emf': No such file or directory"],
            "error": "Process completed with exit code 1."}
    assert ef.classify(late) == "Missing file or command"               # closer than the TIMEOUT env line
    assert ef.classify({"error": "Process completed with exit code 127."}) == "Missing file or command"
    assert ef.classify({"excerpt": ["all good"], "error": ""}) is None


def _run(i, date, *jobs):
    return {"id": i, "date": date, "url": f"u{i}", "jobs": [{"name": n, "failed_steps": s} for n, s in jobs]}


def test_common_reasons_rank_by_count_then_recency():
    runs = [
        _run(1, "2026-10-01", ("smoke (a) / provision", ["upgrade", "SOS"]), ("smoke (b) / provision", ["upgrade"])),
        _run(2, "2026-10-05", ("smoke (c) / provision", ["upgrade"])),
        _run(3, "2026-10-09", ("gcp / build", ["Build Images"])),
        _run(4, "2026-10-08", ("iso / create", ["Create ISO"])),
        {"id": 5, "date": "2026-10-10", "url": "u5"},                    # no jobs read
    ]
    ranked = ef.common_reasons(runs)
    assert [(g["signature"], g["count"]) for g in ranked] == [
        ("smoke / provision › upgrade", 2),                              # counted once per run
        ("gcp / build › Build Images", 1), ("iso / create › Create ISO", 1)]   # ties: newest first
    assert ranked[0]["last_seen"] == "2026-10-05" and [r["id"] for r in ranked[0]["runs"]] == [2, 1]
    assert [g["count"] for g in ef.common_reasons(runs, min_count=2)] == [2]
    assert len(ef.common_reasons(runs, top=1)) == 1


RUN = {"id": 9, "run_number": 1625, "run_attempt": 2, "conclusion": "failure", "status": "completed",
       "created_at": "2026-10-27T01:06:00Z", "head_branch": "master", "head_sha": "07e3f26616b3",
       "event": "schedule", "url": "https://gh/run/9", "title": "stream-build-6_3_x"}


def _job(**over):
    parsed = ef.parse_log(LOG)
    job = {"name": "nightly / job (rocky)", "url": "https://gh/job/1", "failed_steps": ["Run setup", "SOS"],
           "signature": "nightly / job › Run setup", "parsed": parsed, "log_error": None,
           "category": ef.classify(parsed)}
    return {**job, **over}


def _doc(**over):
    a = {"repo": "o/r", "workflow": "nightly.yml", "window_days": 30, "run": RUN, "jobs": [_job()],
         "reasons": [{"signature": "nightly / job › Run setup", "count": 2,
                      "runs": [{"id": 9, "date": "2026-10-27", "url": "u9"},
                               {"id": 8, "date": "2026-10-26T01:00:00Z", "url": "u8"}]}],
         "failed_total": 23, "last_success": {"id": 7, "run_number": 1622, "url": "u7",
                                               "created_at": "2026-10-24T15:39:00Z", "head_sha": "187c8653a2ff"},
         "changes": {"total": 2, "commits": [{"sha": "aaa", "message": "Old (#1)\n\nbody", "author": "A", "url": "ca"},
                                             {"sha": "bbb", "message": "New (#2)", "author": "B", "url": "cb"}]},
         "history_error": None, "generated": "2026-10-28 10:50 UTC"}
    return ef.markdown({**a, **over})


def test_markdown_full_document():
    md = _doc()
    assert md.startswith("# EMF nightly failure: run #1625\n")
    assert "attempt 2, started 2026-10-27 01:06 UTC (schedule)" in md and "Run title" not in md   # schedule
    assert "failed at *Run setup* (Timeout, keyword guess): `Error occurred: Operation" in md
    assert "- **Later failed steps:** SOS" in md and "**Failing action inside the step:** Start Cluster" in md
    assert "Waiting for stonith-co-es-pm-155  (×4)" in md and "```text" in md
    assert "2 of 23 failed runs. Others: [2026-10-26](u8)" in md
    assert "**Last success:** [#1622](u7)" in md and "**Commits since then:** 2" in md
    assert md.index("[bbb](cb) New (#2) (B)") < md.index("[aaa](ca) Old (#1) (A)")    # newest first
    assert "—" not in md and "–" not in md                                    # no em/en dashes


def test_markdown_variants():
    push = {**RUN, "event": "push", "title": "EX-1 fix `x`", "run_attempt": None, "run_number": None}
    md = _doc(run=push, jobs=[], reasons=[], last_success=None)
    assert "# EMF nightly failure: run #9" in md and "- **Run title:** EX-1 fix `x`" in md and "attempt 1" in md
    assert "No failed jobs were reported" in md and "No successful run in the 30 days" in md
    assert "Run history unavailable: boom" in _doc(history_error="boom")
    same = _doc(last_success={"id": 7, "url": "u7", "head_sha": RUN["head_sha"], "created_at": None})
    assert "Same commit as this run" in same and "[#7](u7) on ?, commit" in same
    assert "Changes could not be listed: nope" in _doc(changes={"error": "nope"})
    many = {"total": 30, "commits": [{"sha": f"s{i}", "message": f"m{i}", "author": "A", "url": "c"}
                                     for i in range(30)]}
    assert "and 5 more" in _doc(changes=many)
    assert "**Commits since then:**" not in _doc(changes=None)


def test_markdown_job_sections_and_pattern_edges():
    others = [{"id": i, "date": f"2026-10-{i:02d}", "url": f"u{i}"} for i in range(1, 12)]
    md = _doc(jobs=[_job(log_error="error connecting to blob", parsed=None, category=None),
                    _job(parsed=ef.parse_log("no markers"), category=None, failed_steps=[]),
                    _job(parsed={"actions": [], "error": "e", "exit_code": None, "key_lines": [],
                                 "excerpt": ["only ```fence``` line"]}, category=None,
                         signature="other › x"),
                    _job(parsed={"actions": [], "error": "first line", "exit_code": None, "key_lines": [],
                                 "excerpt": []}, category=None)],          # error with nothing before it
              reasons=[{"signature": "nightly / job › Run setup", "count": 12, "runs": others}])
    assert "The failed-step log could not be downloaded: error connecting to blob" in md
    assert "No `##[error]` line was found" in md and "- **Failed step:** (none reported)" in md
    assert "only '''fence''' line" in md and "Error lines before the failure" not in md.split("### 3.")[1]
    assert "and 2 more" in md                                           # 10 others (not run 9), 8 listed
    assert "`other › x`: no other failed run in the window had this failure." in md
    assert "failed at *(no failed step reported)*." in md               # no step, no context line
