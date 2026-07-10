"""Summarize GitHub Actions runs into an EMF build-stability trend.

A run "passed" when its conclusion is ``success`` and "failed" when
``failure``. Everything else (cancelled / skipped / timed_out / still running)
is neither and is excluded from the pass-rate denominator. Pass rate =
passed / (passed + failed), overall and bucketed by day for the trend graph —
mirroring the Lustre stability shape so the frontend chart is reused.
"""

from __future__ import annotations

from collections import OrderedDict


def _day(ts: object) -> str | None:
    return str(ts)[:10] if ts else None


def _rate(passed: int, failed: int) -> float | None:
    denom = passed + failed
    return round(passed / denom * 100, 1) if denom else None


def summarize(runs: list[dict], *, days: int | None = None) -> dict:
    passed = sum(1 for r in runs if r.get("conclusion") == "success")
    failed = sum(1 for r in runs if r.get("conclusion") == "failure")
    return {
        "runs": len(runs),
        "passed": passed,
        "failed": failed,
        "other": len(runs) - passed - failed,
        "pass_rate": _rate(passed, failed),
        "days": days,
    }


def trend(runs: list[dict]) -> list[dict]:
    buckets: "OrderedDict[str, dict]" = OrderedDict()
    for r in runs:
        day = _day(r.get("created_at"))
        if not day:
            continue
        b = buckets.setdefault(day, {"date": day, "runs": 0, "passed": 0, "failed": 0})
        b["runs"] += 1
        if r.get("conclusion") == "success":
            b["passed"] += 1
        elif r.get("conclusion") == "failure":
            b["failed"] += 1
    out = []
    for day in sorted(buckets):
        b = buckets[day]
        b["pass_rate"] = _rate(b["passed"], b["failed"])
        out.append(b)
    return out


def run_rows(runs: list[dict], *, limit: int = 60) -> list[dict]:
    rows = [{
        "date": r.get("created_at"),
        "conclusion": r.get("conclusion") or r.get("status"),
        "branch": r.get("head_branch"),
        "event": r.get("event"),
        "url": r.get("url"),
    } for r in runs]
    rows.sort(key=lambda x: str(x["date"] or ""), reverse=True)
    return rows[:limit]


def report(runs: list[dict], *, days: int | None = None) -> dict:
    return {"summary": summarize(runs, days=days), "trend": trend(runs),
            "runs": run_rows(runs)}
