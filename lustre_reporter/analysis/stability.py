"""Turn Maloo test sessions into stability metrics and a daily trend.

A session is "clean" when it recorded no failed and no aborted test sets.
We report both a session-level pass rate (clean sessions / sessions) and a
test-set-level pass rate (passed test sets / total), bucketed by day for the
trend graph.
"""

from __future__ import annotations

from collections import OrderedDict


def _day(submission: object) -> str | None:
    if not submission:
        return None
    return str(submission)[:10]  # "YYYY-MM-DD ..." -> "YYYY-MM-DD"


def _int(v: object) -> int:
    try:
        return int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _clean(s: dict) -> bool:
    return _int(s.get("failed")) == 0 and _int(s.get("aborted")) == 0


def _rate(numer: int, denom: int) -> float | None:
    return round(numer / denom * 100, 1) if denom else None


def summarize(sessions: list[dict]) -> dict:
    total = len(sessions)
    clean = sum(1 for s in sessions if _clean(s))
    tp = sum(_int(s.get("passed")) for s in sessions)
    tf = sum(_int(s.get("failed")) for s in sessions)
    ta = sum(_int(s.get("aborted")) for s in sessions)
    tt = sum(_int(s.get("total")) for s in sessions)
    return {
        "sessions": total,
        "clean_sessions": clean,
        "failed_sessions": total - clean,
        "session_pass_rate": _rate(clean, total),
        "testsets_passed": tp,
        "testsets_failed": tf,
        "testsets_aborted": ta,
        "testsets_total": tt,
        "testset_pass_rate": _rate(tp, tt),
    }


def trend(sessions: list[dict]) -> list[dict]:
    buckets: "OrderedDict[str, dict]" = OrderedDict()
    for s in sessions:
        day = _day(s.get("submission"))
        if not day:
            continue
        b = buckets.setdefault(day, {
            "date": day, "sessions": 0, "clean": 0,
            "testsets_passed": 0, "testsets_failed": 0, "testsets_total": 0,
        })
        b["sessions"] += 1
        if _clean(s):
            b["clean"] += 1
        b["testsets_passed"] += _int(s.get("passed"))
        b["testsets_failed"] += _int(s.get("failed"))
        b["testsets_total"] += _int(s.get("total"))
    out = []
    for day in sorted(buckets):
        b = buckets[day]
        b["session_pass_rate"] = _rate(b["clean"], b["sessions"])
        b["testset_pass_rate"] = _rate(b["testsets_passed"], b["testsets_total"])
        out.append(b)
    return out


def session_rows(sessions: list[dict]) -> list[dict]:
    rows = [{
        "session_id": s.get("session_id"),
        "date": s.get("submission"),
        "host": s.get("test_host"),
        "group": s.get("test_group"),
        "name": s.get("test_name"),
        "passed": _int(s.get("passed")),
        "failed": _int(s.get("failed")),
        "aborted": _int(s.get("aborted")),
        "total": _int(s.get("total")),
        "enforcing": s.get("enforcing"),
        "clean": _clean(s),
        "url": s.get("url"),
    } for s in sessions]
    rows.sort(key=lambda r: str(r["date"] or ""), reverse=True)
    return rows


def report(sessions: list[dict]) -> dict:
    return {
        "summary": summarize(sessions),
        "trend": trend(sessions),
        "sessions": session_rows(sessions),
    }
